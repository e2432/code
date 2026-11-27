#!/usr/bin/env python3
"""Bounded, read-only AFE Harbor inspection. Never execute package code."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import sys
from afe_contract import PROTOCOL_VERSION, validate_metadata, validate_reference, validate_result

VERSION = '2.0.0'
GROUPS = {'F1':'必需结构与入口','F2':'配置可解析与字段规范','F3':'agent/verifier配置边界',
          'F4':'文件引用与入口契约','F5':'依赖、数据与版本声明','F6':'可见范围与工程卫生线索','F7':'Harbor lint'}
PRIORITY = {'不适用':0,'通过':1,'提醒':2,'待核实':3,'不通过':4}
TEXT_EXT = {'.md','.txt','.toml','.json','.yaml','.yml','.sh','.py','.r','.js','.ts','.jl','.ini','.cfg'}
CACHES = {'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache'}
SKIP_DIRS = {'.git','.venv','venv','node_modules'} | CACHES


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_json(path, data, root, overwrite=False):
    path = Path(path).resolve()
    if inside(path, root):
        raise ValueError('输出必须位于源任务包之外')
    if path.exists() and not overwrite:
        raise ValueError('输出已存在；使用新文件或显式 --overwrite')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w' if overwrite else 'x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Inspector:
    def __init__(self, root, max_entries=12000, max_text_bytes=524288, max_total_bytes=8388608, build_contexts=None):
        self.root = Path(root).resolve()
        self.max_entries, self.max_text_bytes, self.max_total_bytes = max_entries, max_text_bytes, max_total_bytes
        self.checks, self.files, self.read_files, self.skipped = [], [], [], []
        self.text_cache, self.entries, self.bytes_read = {}, 0, 0
        self.walk_complete = True
        self.afe_metadata = None
        self.config_data = {}
        self.content_not_scanned, self.dockerfiles_checked, self.evidence_candidates = [], [], []
        self.build_contexts={'environment/Dockerfile':'environment','tests/Dockerfile':'tests'}
        for dockerfile,context in (build_contexts or {}).items():
            for value in [dockerfile,context]:
                path=Path(value)
                if path.is_absolute() or '..' in path.parts or not inside((self.root/path).resolve(),self.root):
                    raise ValueError('build-context必须使用包内相对路径，不得经链接指向包外')
            self.build_contexts[dockerfile]=context

    def add(self, code, status, reason, evidence):
        self.checks.append({'id':code,'group':code.split('.')[0],'status':status,'reason':reason,
                            'evidence':evidence if isinstance(evidence,list) else [evidence]})

    def read(self, relative):
        relative = str(relative)
        if relative in self.text_cache:
            return self.text_cache[relative]
        path, reason = self.root / relative, None
        try:
            info = path.lstat()
            if not inside(path.resolve(), self.root):reason='链接目标在包外，未读取'
            elif not stat.S_ISREG(info.st_mode):reason='链接或特殊文件，未读取'
            elif info.st_size > self.max_text_bytes:reason='超过单文件文本预算'
            elif self.bytes_read + info.st_size > self.max_total_bytes:reason='超过总文本预算'
            else:
                fd=os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | getattr(os,'O_NOFOLLOW',0))
                with os.fdopen(fd,'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        reason,raw='读取时已不是普通文件',b''
                    else:raw=stream.read(min(self.max_text_bytes, self.max_total_bytes-self.bytes_read)+1)
                if not reason and (len(raw)>self.max_text_bytes or self.bytes_read+len(raw)>self.max_total_bytes):reason='读取时超过预算'
                if not reason:
                    self.bytes_read += len(raw)
                    text=raw.decode('utf-8-sig')
                    self.read_files.append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
                    self.text_cache[relative]=text
                    return text
        except (OSError, RuntimeError, UnicodeError) as exc:
            reason=type(exc).__name__+'：未能读取文本'
        self.skipped.append({'path':relative,'reason':reason})
        self.text_cache[relative]=None
        return None

    def required(self):
        required=[('task.toml','file'),('instruction.md','file'),('tests/test.sh','file')]
        env=self.config_data.get('environment',{})
        verifier=self.config_data.get('verifier',{})
        venv=verifier.get('environment',{}) if isinstance(verifier,dict) else {}
        for path,settings in [('environment/Dockerfile',env),('tests/Dockerfile',venv)]:
            image=settings.get('docker_image') if isinstance(settings,dict) else None
            if isinstance(image,str) and image.strip() and not (self.root/path).exists():
                self.add('F1.required','通过','已声明预构建镜像，Dockerfile 可省略；镜像内容和可用性另核',path)
            else:required.append((path,'file'))
        for rel,kind in required:
            try:
                info=(self.root/rel).lstat()
                if stat.S_ISLNK(info.st_mode):self.add('F1.required','待核实','必需入口是链接，需核对可读性与边界',rel)
                elif (kind=='file' and not stat.S_ISREG(info.st_mode)) or (kind=='dir' and not stat.S_ISDIR(info.st_mode)):
                    self.add('F1.required','不通过','必需路径类型不符：预期'+kind,rel)
                elif kind=='file' and info.st_size==0:self.add('F1.required','不通过','必需文件为空',rel)
                else:self.add('F1.required','通过','必需'+kind+'存在',rel)
            except FileNotFoundError:self.add('F1.required','不通过','缺少AFE指南要求的必需路径',rel)
            except OSError:self.add('F1.required','待核实','无法访问路径，不能认定不存在',rel)

    def walk(self):
        pending=[self.root]
        while pending:
            directory=pending.pop()
            try:
                with os.scandir(str(directory)) as entries:
                    for entry in entries:
                        self.entries+=1
                        if self.entries>self.max_entries:
                            self.walk_complete=False
                            self.skipped.append({'path':str(directory.relative_to(self.root)),'reason':'达到目录条目预算，后续未遍历'})
                            return
                        rel=str(Path(entry.path).relative_to(self.root))
                        if entry.is_symlink():
                            self.add('F6.symlink','提醒','未跟随链接；需核对声明输入及可见范围',rel)
                            self.skipped.append({'path':rel,'reason':'符号链接未跟随'})
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in CACHES:self.add('F6.cache','不通过','含指南禁止的缓存目录',rel)
                            if entry.name in SKIP_DIRS:self.skipped.append({'path':rel,'reason':'未遍历缓存、依赖或Git历史目录'})
                            elif len(Path(rel).parts)>32:
                                self.walk_complete=False
                                self.skipped.append({'path':rel,'reason':'超过目录深度限制'})
                            else:pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            self.files.append(rel)
                            if entry.name=='.DS_Store' or entry.name.endswith('.pyc'):
                                self.add('F6.cache','不通过','含指南禁止的缓存/系统文件',rel)
                        else:self.skipped.append({'path':rel,'reason':'特殊文件未读取'})
            except OSError:
                self.walk_complete=False
                self.skipped.append({'path':str(directory.relative_to(self.root)),'reason':'目录无法遍历'})

    def config(self):
        text=self.read('task.toml')
        if text is None:
            self.add('F2.parse','待核实','配置未读取，未解析','task.toml')
            self.add('F3.config','待核实','没有可解析配置，边界未核对','task.toml')
            return
        try:
            try:import tomllib as toml
            except ImportError:import tomli as toml
        except ImportError:
            self.add('F2.parser','待核实','本机缺tomllib/tomli，不是题包解析失败','task.toml')
            self.add('F3.config','待核实','未解析配置，边界未核对','task.toml')
            return
        try:data=toml.loads(text)
        except ValueError:
            self.add('F2.parse','不通过','TOML语法无效；不输出可能含私有值的解析上下文','task.toml')
            self.add('F3.config','待核实','配置语法无效，未推断实际隔离状态','task.toml')
            return
        self.add('F2.parse','通过','TOML可解析','task.toml')
        self.config_data=data
        self.add('F2.schema','通过' if data.get('schema_version')=='1.4' else '不通过','项目约定schema_version为字符串1.4','task.toml:schema_version')
        sections={}
        for key in ['task','metadata','verifier','agent','environment']:
            value=data.get(key)
            valid=isinstance(value,dict)
            self.add('F2.section','通过' if valid else '不通过','应存在TOML段：'+key,'task.toml:['+key+']')
            sections[key]=value if valid else {}
        name=sections['task'].get('name')
        self.add('F2.name','通过' if isinstance(name,str) and re.fullmatch(r'afe/[a-z0-9][a-z0-9_-]*',name) else '不通过',
                 'AFE指南约定task.name为afe/<科学任务名>；这是项目命名要求','task.toml:task.name')
        self.add('F2.directory','通过' if re.fullmatch(r'[a-z0-9][a-z0-9_-]*',self.root.name) else '提醒',
                 '目录建议仅用小写字母、数字、下划线和短横线；不强令其等于task.name','任务目录名')
        task_id=data.get('task_id',sections['task'].get('task_id'))
        if task_id is not None:self.add('F2.task_id','通过' if isinstance(task_id,str) and task_id==self.root.name else '不通过','显式task_id应与目录名一致','task.toml:task_id')
        for section,key,zero in [('verifier','timeout_sec',False),('agent','timeout_sec',False),('environment','build_timeout_sec',False),('environment','cpus',False),('environment','memory_mb',False),('environment','storage_mb',False),('environment','gpus',True)]:
            value=sections[section].get(key)
            valid=type(value) in (int,float) and (type(value) is int or math.isfinite(value)) and (value>=0 if zero else value>0)
            self.add('F2.resource','通过' if valid else '不通过','资源/时间须为有限'+('非负' if zero else '正')+'数；不判断科学预算是否足够','task.toml:'+section+'.'+key)
        self.afe_metadata=sections['metadata'].get('afe')
        if self.afe_metadata is None:
            self.add('F2.metadata','提醒','未声明 AFE 1.0 协议；按旧包检查并记录元信息/评分接口迁移事项，不自动认定不兼容 Harbor','task.toml:[metadata]')
        elif not isinstance(self.afe_metadata,dict):
            self.add('F2.metadata','不通过','metadata.afe 应为表','task.toml:[metadata.afe]')
        elif self.afe_metadata.get('protocol_version') != PROTOCOL_VERSION:
            self.add('F2.metadata','待核实','未声明或尚不支持的 AFE 协议版本；不按 1.0 猜测','task.toml:metadata.afe.protocol_version')
        else:
            errors,warnings=validate_metadata(self.afe_metadata)
            self.add('F2.metadata','不通过' if errors else '通过','；'.join(errors) if errors else 'AFE 1.0 元信息类型与必填项符合约定','task.toml:[metadata.afe]')
            for message in warnings:self.add('F2.metadata_note','提醒',message,'task.toml:[metadata.afe]')
        verifier=sections['verifier']
        self.add('F3.separate','通过' if verifier.get('environment_mode')=='separate' else '不通过','AFE要求verifier.environment_mode=separate','task.toml:verifier.environment_mode')
        artifacts=data.get('artifacts')
        sources=[x.get('source') if isinstance(x,dict) else x for x in artifacts] if isinstance(artifacts,list) else []
        valid=bool(sources) and all(isinstance(x,str) and x.startswith('/') and '..' not in PurePosixPath(x).parts and '\x00' not in x for x in sources)
        if valid:
            valid=all(not isinstance(x,dict) or ('service' not in x or isinstance(x['service'],str) and bool(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',x['service']))) for x in artifacts)
        self.add('F3.artifacts','通过' if valid else '不通过','artifacts应为非空列表，条目可为绝对容器路径或含 source/可选 service 的对象','task.toml:artifacts')
        if valid and any(x in ['/','/root','/app','/tests','/solution'] for x in sources):self.add('F3.artifacts_scope','提醒','artifacts范围宽或涉及私有材料，需核对必要性','task.toml:artifacts')
        env=verifier.get('environment',{})
        network=env.get('network_mode') if isinstance(env,dict) else None
        self.add('F3.network','通过' if network=='no-network' else '提醒','verifier网络须与依赖一致；指南默认no-network，例外需说明','task.toml:verifier.environment.network_mode')

    def docker(self, rel):
        text=self.read(rel)
        if text is None:
            self.add('F4.docker_read','待核实','Dockerfile未读取，构建引用未检查',rel)
            return
        declared_context=self.build_contexts.get(rel)
        context=self.root/declared_context if declared_context is not None else None
        self.dockerfiles_checked.append({'path':rel,'build_context':declared_context,'context_source':'AFE主目录约定或调用者根据构建声明指定' if context is not None else '未确定'})
        if context is None:
            self.add('F4.build_context','待核实','额外Dockerfile的真实构建上下文未确定；阅读Compose/构建声明后用--build-context指定，不按文件所在目录猜测',rel)
        stages,count=set(),0
        for n,line in enumerate(re.sub(r'\\\r?\n',' ',text).splitlines(),1):
            line=line.strip()
            if not line or line.startswith('#'):continue
            evidence=rel+':逻辑行'+str(n)
            m=re.match(r'FROM\s+(?:--\S+\s+)*([^\s]+)(?:\s+AS\s+(\S+))?',line,re.I)
            if m:
                count+=1
                image,alias=m.groups()
                if image.lower()=='scratch' or image.lower() in stages:status,reason='通过','空基础镜像或已定义构建阶段'
                elif '$' in image:status,reason='待核实','基础镜像含变量，需解析参数'
                elif image.endswith(':latest'):status,reason='提醒','latest为浮动tag，需说明版本固定方式'
                elif '@sha256:' in image or ':' in image.rsplit('/',1)[-1]:status,reason='通过','声明了tag或digest，未联网验证镜像'
                else:status,reason='不通过','基础镜像没有指南要求的tag或digest'
                self.add('F5.image',status,reason,evidence)
                if alias:stages.add(alias.lower())
            m=re.match(r'(COPY|ADD)\s+(.+)',line,re.I)
            if not m:continue
            if context is None:continue
            rest=m.group(2)
            if re.search(r'--from(?:=|\s)',rest):continue
            rest=re.sub(r'^(?:--[\w-]+(?:=\S+)?\s+)+','',rest)
            try:
                parts=json.loads(rest) if rest.startswith('[') else shlex.split(rest)
                if not isinstance(parts,list) or len(parts)<2 or not all(isinstance(p,str) for p in parts):raise ValueError()
            except (ValueError,TypeError):
                self.add('F4.copy_parse','待核实','复杂构建指令未解析',evidence)
                continue
            for source in parts[:-1]:
                if any(x in source for x in ['$', '*', '?', '[']) or source.startswith(('http:','https:','git@','<<')):
                    self.add('F4.copy_dynamic','待核实','动态、通配、远程或内联来源未验证',evidence)
                    continue
                if '..' in PurePosixPath(source).parts:
                    self.add('F4.copy_boundary','提醒','构建引用包含上级路径，需确认真实上下文',evidence)
                    continue
                candidate=context/source.lstrip('/')
                try:
                    if not inside(candidate.resolve(),self.root):
                        self.add('F4.copy_boundary','待核实','构建来源解析到包外，未读取',evidence)
                        continue
                    candidate.stat()
                    self.add('F4.copy_source','通过','按记录的构建上下文核对，来源存在；dockerignore语义另审',[evidence,str(candidate.relative_to(self.root))])
                except FileNotFoundError:self.add('F4.copy_source','不通过','按记录的构建上下文核对，本地来源不存在',[evidence,str(candidate.relative_to(self.root))])
                except (OSError,RuntimeError):self.add('F4.copy_source','待核实','不能访问构建来源',evidence)
        if not count:self.add('F5.image','不通过','未发现FROM基础镜像声明',rel)

    def texts(self):
        for rel in sorted(self.files):
            p=Path(rel)
            if rel not in self.text_cache and p.suffix.lower() not in TEXT_EXT and p.name not in {'Dockerfile','.dockerignore','LICENSE','SHA256SUMS'}:
                self.content_not_scanned.append({'path':rel,'reason':'文件类型未纳入自动文本扫描；按需人工检查元数据/小样本'})
                continue
            text=self.read(rel)
            if text is None:continue
            solver=rel=='instruction.md' or rel.startswith('environment/')
            for n,line in enumerate(text.splitlines(),1):
                evidence=rel+':'+str(n)
                if re.search(r'(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[\x22\x27][A-Za-z0-9_./+=-]{12,}[\x22\x27]',line,re.I):
                    self.add('F6.credential','提醒','疑似字面量凭据，值已隐去；在源文件核对是否为占位符',evidence)
                if solver and re.search(r'/mnt/shared-storage|/home/[^\s/]+/|/Users/[^\s/]+/|[A-Za-z]:\\Users\\',line):
                    self.add('F6.host_path','提醒','发现宿主路径线索，可能为声明挂载；需核对',evidence)
                if solver and p.name=='Dockerfile' and re.search(r'\b(?:COPY|ADD|RUN)\b.*(?:tests/|solution/|authoring/|PRIVATE/)',line,re.I):
                    self.add('F6.private_copy','提醒','解题环境构建引用私有材料名称，需核对上下文与dockerignore',evidence)
        scorer=[p for p in self.files if p.startswith('tests/') and Path(p).suffix.lower() in {'.py','.r','.js','.jl','.sh'} and p!='tests/test.sh']
        self.add('F1.scorer','通过' if scorer else '提醒','发现评分实现候选，实际科学作用另审' if scorer else '未识别独立评分脚本，可能是test.sh内嵌或模块实现',scorer[:6] or ['tests/test.sh'])
        reward=[p for p,t in self.text_cache.items() if t and p.startswith('tests/') and re.search(r'reward\.(?:txt|json)',t)]
        self.add('F4.reward','通过' if reward else '待核实','发现reward字面量，不证明实际写入正确' if reward else '未静态识别reward接口，需跟踪实际评分逻辑',reward or ['tests/'])
        entry=self.text_cache.get('tests/test.sh')
        docker=self.text_cache.get('tests/Dockerfile') or ''
        maps_tests=self.build_contexts.get('tests/Dockerfile')=='tests' and bool(re.search(r'COPY\s+\.\s+/tests/?(?:\s|$)',docker,re.M))
        if entry:
            for n,line in enumerate(entry.splitlines(),1):
                if line.lstrip().startswith('#'):continue
                for target in re.findall(r'\b(?:python3?|bash|sh|Rscript|node|julia)\s+[\x22\x27]?(/tests/[\w./-]+)',line):
                    rel='tests/'+target[len('/tests/'):]
                    if '..' in PurePosixPath(rel).parts:self.add('F4.script_ref','待核实','脚本引用有上级路径，需人工跟踪',f'tests/test.sh:{n}')
                    elif maps_tests:
                        candidate=self.root/rel
                        try:
                            if not inside(candidate.resolve(),self.root) or candidate.is_symlink():
                                status,reason='待核实','入口是链接或解析到包外，未读取'
                            elif candidate.is_file():status,reason='通过','按COPY . /tests映射，包内入口存在'
                            else:status,reason='待核实','源码映射中未找到入口，需核对是否在构建/运行时生成'
                        except (OSError,RuntimeError):status,reason='待核实','不能核对脚本容器映射'
                        self.add('F4.script_ref',status,reason,[f'tests/test.sh:{n}',rel])
                    else:self.add('F4.script_ref','待核实','脚本容器映射未静态确认',[f'tests/test.sh:{n}',rel])
        provenance=[p for p in self.files if p.startswith('authoring/provenance/')]
        evidence=[p for p in self.files if p.startswith('authoring/evidence/') or re.search(r'(?:oracle|nop|validation|lint|manifest|checksum)',Path(p).name,re.I)]
        def evidence_priority(path):
            name=Path(path).name.lower()
            if '/schemas/' in path or name.endswith('.schema.json'):return (4,0,path)
            for i,word in enumerate(['oracle','reference','nop','lint','partial']):
                if word in name and 'result' in name and Path(path).suffix.lower()=='.json':return (0,i,path)
            for i,word in enumerate(['binding','validation','serialization','scientific_metrics']):
                if word in name and Path(path).suffix.lower() in {'.json','.md'}:return (1,i,path)
            if path.startswith('authoring/evidence/'):return (2,0,path)
            return (3,0,path)
        evidence.sort(key=evidence_priority)
        self.evidence_candidates=evidence
        self.add('F5.provenance','通过' if provenance else '待核实','发现溯源文件，内容另审' if provenance else '任务目录内未定位溯源文件；核对已提供的网页信息或包外补充材料，不强制authoring目录',provenance[:6] or ['任务目录扫描范围；不含包外补充材料或网页'])
        self.add('F5.evidence','提醒' if evidence else '待核实','优先列结果与版本绑定候选；文件名不是有效证据，完整列表见coverage.evidence_candidates' if evidence else '未发现常见命名的记录，可核对补充材料中的验证记录；提议可尚未验证',evidence[:8] or ['任务目录扫描范围'])

    def protocol(self):
        afe=self.afe_metadata
        if not isinstance(afe,dict) or afe.get('protocol_version') != PROTOCOL_VERSION:return
        mapping=afe.get('score_mapping')
        locations=[]
        if isinstance(mapping,dict) and isinstance(mapping.get('url'),str):locations.append((mapping['url'],False))
        refs=afe.get('reference_urls',[])
        if isinstance(refs,list):locations.extend((url,True) for url in refs if isinstance(url,str))
        for url,is_reference in locations:
            if url.startswith('https://'):
                self.add('F4.afe_resource','待核实','外部资源未自动下载；核对访问和冻结版本',url)
                continue
            path=PurePosixPath(url)
            if not url or path.is_absolute() or '..' in path.parts or '://' in url:
                self.add('F4.afe_resource','不通过','资源地址使用包内相对路径或 HTTPS 地址','task.toml:metadata.afe')
                continue
            target=self.root/url
            if not inside(target.resolve(),self.root):
                self.add('F4.afe_resource','待核实','资源指向包外，未读取',url)
                continue
            if not target.exists():
                self.add('F4.afe_resource','不通过','声明的包内资源不存在',url)
                continue
            self.add('F4.afe_resource','通过','声明的包内资源存在；实际使用由内容审核确认',url)
            if is_reference:
                rel=str((target/'info.json' if target.is_dir() else target).relative_to(self.root))
                if Path(rel).name != 'info.json':
                    self.add('F4.reference','不通过','参考地址应定位方法目录或 info.json',url)
                    continue
                text=self.read(rel)
                if text is None:
                    self.add('F4.reference','不通过' if not (self.root/rel).exists() else '待核实','未读取方法 info.json',rel)
                    continue
                try:
                    errors,warnings=validate_reference(json.loads(text))
                except ValueError:errors,warnings=['info.json 不是合法 JSON'],[]
                self.add('F4.reference','不通过' if errors else '通过','；'.join(errors) if errors else '参考信息结构符合约定；不要求代码或成绩',rel)
        result_files=[p for p in self.files if Path(p).name=='afe_result.json']
        for rel in result_files:
            text=self.read(rel)
            if text is None:continue
            try:errors,warnings=validate_result(json.loads(text),afe.get('supports_over_target'))
            except ValueError:errors,warnings=['结果不是合法 JSON'],[]
            self.add('F4.afe_result','不通过' if errors else ('提醒' if warnings else '通过'),'；'.join(errors or warnings) if errors or warnings else '所附结果结构符合约定；不证明本轮运行成功',rel)
        if not result_files:self.add('F4.afe_result','待核实','未附运行结果；阅读评分实现核对输出，不要求审核时运行任务','tests/')

    def run(self):
        self.walk()
        self.config()
        self.required()
        dockerfiles={p for p in self.build_contexts if (self.root/p).exists()} | {p for p in self.files if Path(p).name=='Dockerfile' or Path(p).name.startswith('Dockerfile.') or Path(p).name.endswith('.Dockerfile')}
        for rel in sorted(dockerfiles):self.docker(rel)
        self.texts()
        self.protocol()
        incomplete=bool(self.skipped or self.content_not_scanned)
        self.add('F6.coverage','提醒' if incomplete else '通过','遍历不等于正文全查；未读取范围见coverage.skipped与content_not_scanned，不因此认定题包异常' if incomplete else '预算内可识别文本已扫描；运行行为未查','扫描记录')
        if not self.walk_complete:self.add('F1.coverage','待核实','遍历未完成，不得据扫描结果宣称全包齐全','coverage')
        self.add('F7.lint','待核实','发现Harbor命令但未执行，须核对版本与已有记录' if shutil.which('harbor') else '本机无Harbor命令；指定版本lint未执行，可核对已有记录','工具环境')
        groups=[]
        for key,title in GROUPS.items():
            items=[c for c in self.checks if c['group']==key]
            groups.append({'id':key,'name':title,'status':max((c['status'] for c in items),key=PRIORITY.get),'counts':dict(Counter(c['status'] for c in items))})
        return {'schema_version':'1.0','rule_version':VERSION,'profile':'afe-contract-1.0' if isinstance(self.afe_metadata,dict) and self.afe_metadata.get('protocol_version')==PROTOCOL_VERSION else 'rex-legacy','generated_at':datetime.now(timezone.utc).isoformat(),
                'package_root':str(self.root),'task_id':self.root.name,'mode':'static-only','groups':groups,'checks':self.checks,
                'coverage':{'entries_seen':self.entries,'regular_files_seen':len(self.files),'walk_complete':self.walk_complete,'text_bytes_read':self.bytes_read,
                            'read_files':self.read_files,'skipped':self.skipped,'content_not_scanned':self.content_not_scanned,
                            'dockerfiles_checked':self.dockerfiles_checked,'evidence_candidates':self.evidence_candidates,
                            'limits':{'max_entries':self.max_entries,'max_text_bytes':self.max_text_bytes,'max_total_bytes':self.max_total_bytes},
                            'not_executed':['镜像构建','参考解','评分器','任务测试','Harbor lint','远程服务','大数据下载']},
                'summary':{'counts':dict(Counter(c['status'] for c in self.checks)),'has_failures':any(c['status']=='不通过' for c in self.checks),'note':'结构事实与线索，不是科学正确性、运行成功或接收决定'}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_dir')
    parser.add_argument('--output',required=True)
    parser.add_argument('--overwrite',action='store_true')
    parser.add_argument('--max-entries',type=int,default=12000)
    parser.add_argument('--max-text-bytes',type=int,default=524288)
    parser.add_argument('--max-total-bytes',type=int,default=8388608)
    parser.add_argument('--build-context',action='append',default=[],metavar='DOCKERFILE=CONTEXT',help='根据构建声明指定包内相对路径，可重复；不执行Compose')
    args=parser.parse_args()
    try:
        root=Path(args.task_dir).resolve()
        if not root.is_dir():raise ValueError('输入必须是可访问的单任务目录；不自动解压归档')
        if min(args.max_entries,args.max_text_bytes,args.max_total_bytes)<1:raise ValueError('扫描预算必须为正数')
        destination=Path(args.output).resolve()
        if inside(destination,root):raise ValueError('输出必须位于源任务包之外')
        if destination.exists() and not args.overwrite:raise ValueError('输出已存在；使用新文件或 --overwrite')
        contexts={}
        for value in args.build_context:
            if '=' not in value:raise ValueError('--build-context格式应为Dockerfile相对路径=上下文相对目录')
            key,context=value.split('=',1)
            if not key or not context:raise ValueError('--build-context两侧不得为空')
            contexts[key]=context
        report=Inspector(root,args.max_entries,args.max_text_bytes,args.max_total_bytes,contexts).run()
        write_json(destination,report,root,args.overwrite)
        print(json.dumps({'output':str(destination),'task_id':report['task_id'],**report['summary']},ensure_ascii=False))
        return 1 if report['summary']['has_failures'] else 0
    except (ValueError,OSError) as exc:
        print('检查器错误：'+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':sys.exit(main())
