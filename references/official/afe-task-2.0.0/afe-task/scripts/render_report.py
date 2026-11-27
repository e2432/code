#!/usr/bin/env python3
"""Validate an agent assessment and render one stable Chinese review report."""
import argparse
import json
from pathlib import Path
import sys

from check_structure import GROUPS, PRIORITY, VERSION, inside

DIMENSIONS = {
    'C1': '科学问题与研究价值', 'C2': '任务定义与自洽性',
    'C3': '数据、环境与资源充分性', 'C4': '评分的科学有效性',
    'C5': '评分健壮性与防投机', 'C6': '答案隔离与信息泄漏',
    'C7': '验证证据与可复核性', 'C8': '来源溯源与交付边界',
}
LEVELS = {0: '0 核心不满足', 1: '1 明显缺口', 2: '2 基本达标', 3: '3 充分稳健', None: '待核实'}


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + ' 必须是对象')
    return value


def string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' 必须是非空字符串')
    return value


def strings(value, label, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(label + ' 必须是' + ('' if allow_empty else '非空') + '字符串数组')
    for item in value:
        string(item, label)


def validate(structure, assessment):
    s, a = mapping(structure, 'structure'), mapping(assessment, 'assessment')
    if s.get('schema_version') != '1.0' or a.get('schema_version') != '1.2':
        raise ValueError('仅支持 structure schema 1.0、assessment schema 1.2')
    if s.get('rule_version') != VERSION or s.get('mode') != 'static-only':
        raise ValueError('请使用同版结构脚本的静态结果')
    for key in ['package_root', 'task_id', 'generated_at']:
        string(s.get(key), 'structure.' + key)
    if not Path(s['package_root']).is_absolute():
        raise ValueError('package_root 必须是绝对路径')
    groups = s.get('groups')
    if not isinstance(groups, list) or len(groups) != len(GROUPS):
        raise ValueError('structure 必须包含 F1–F7 七组结果')
    if {mapping(g, 'group').get('id') for g in groups} != set(GROUPS):
        raise ValueError('格式检查组缺失或重复')
    checks = s.get('checks')
    if not isinstance(checks, list) or not checks:
        raise ValueError('缺少原始结构检查项')
    for item in groups + checks:
        mapping(item, 'format item')
        if item.get('status') not in PRIORITY:
            raise ValueError('未知格式状态')
    for item in checks:
        if item.get('group') not in GROUPS:
            raise ValueError('未知格式检查组')
        for key in ['id', 'reason']:
            string(item.get(key), 'check.' + key)
        strings(item.get('evidence'), 'check.evidence')
    for group in groups:
        statuses = [c['status'] for c in checks if c['group'] == group['id']]
        if not statuses or group['status'] != max(statuses, key=PRIORITY.get):
            raise ValueError('结构组结果与明细不一致；不要手改结构结果')
    for key in ['task_title', 'task_version', 'original_level', 'summary', 'recommendation']:
        string(a.get(key), key)
    coverage = mapping(a.get('coverage'), 'coverage')
    strings(coverage.get('read'), 'coverage.read')
    strings(coverage.get('not_verified'), 'coverage.not_verified')
    content = a.get('content')
    if not isinstance(content, list) or len(content) != 8:
        raise ValueError('必须逐项填写 C1–C8，恰好八项')
    if {mapping(c, 'content').get('id') for c in content} != set(DIMENSIONS):
        raise ValueError('C1–C8 编号缺失或重复')
    for item in content:
        score = item.get('score')
        if 'score' not in item or (score is not None and (type(score) is not int or score not in range(4))):
            raise ValueError(item['id'] + '.score 只能为 0、1、2、3 或 null')
        for key in ['reason', 'action']:
            string(item.get(key), item['id'] + '.' + key)
        strings(item.get('evidence'), item['id'] + '.evidence')
    notes = a.get('format_notes')
    if not isinstance(notes, list):
        raise ValueError('format_notes 必须是数组，可为空')
    known_ids = set(GROUPS) | {c['id'] for c in checks}
    for note in notes:
        mapping(note, 'format_note')
        if note.get('check_id') not in known_ids:
            raise ValueError('format_notes 引用了不存在的检查项')
        string(note.get('reason'), 'format_note.reason')
        string(note.get('disposition'), 'format_note.disposition')
        strings(note.get('evidence'), 'format_note.evidence')
    ref = mapping(a.get('reference_solution'), 'reference_solution')
    if type(ref.get('provided')) is not bool:
        raise ValueError('reference_solution.provided 必须为布尔值')
    if set(ref) - {'provided', 'method', 'known_result', 'evidence', 'limitations'}:
        raise ValueError('参考解仅作可选资料记录，不接受旧版验收或作者确认字段')
    if ref['provided']:
        for key in ['method', 'known_result', 'limitations']:
            string(ref.get(key), 'reference_solution.' + key)
        strings(ref.get('evidence'), 'reference_solution.evidence')
    elif set(ref) != {'provided'}:
        raise ValueError('未提供参考解时仅填写 provided=false，不生成虚构结果')
    issues = a.get('issues')
    if not isinstance(issues, list):
        raise ValueError('issues 必须是数组')
    seen = set()
    for issue in issues:
        mapping(issue, 'issue')
        for key in ['id', 'title', 'action']:
            string(issue.get(key), 'issue.' + key)
        strings(issue.get('evidence'), 'issue.evidence')
        if issue['id'] in seen:
            raise ValueError('问题编号重复')
        seen.add(issue['id'])


def cell(value):
    return str(value).replace('|', '\\|').replace('\r', '').replace('\n', '；')


def evidence(items):
    return '；'.join(cell(v) for v in items)


def render(s, a):
    lines = [
        '# ' + cell(a['task_title']) + ' 审核报告', '',
        '任务：`' + cell(s['task_id']) + '`；来源 Level：' + cell(a['original_level']), '',
        '路径：`' + cell(s['package_root']) + '`', '',
        '版本依据：' + cell(a['task_version']), '',
        '审核口径：AFE Harbor 审核 ' + VERSION + '；静态检查与已有证据。结构快照时间：' + s['generated_at'], '',
        '已读范围：' + evidence(a['coverage']['read']), '',
        '未核实：' + evidence(a['coverage']['not_verified']), '',
        '## 结果概览', '',
    ]
    counts = {status: sum(c['status'] == status for c in s['checks']) for status in PRIORITY}
    lines += [
        '格式：' + ('存在不通过项' if counts['不通过'] else '未发现明确格式负项') + '；' +
        '、'.join(k + ' ' + str(v) for k, v in counts.items() if v) + '。这是检查项计数，不是题目得分。', '',
        '内容：' + cell(a['summary']), '',
        '参考解（可选）：' + ('已提供，按已有材料记录。' if a['reference_solution']['provided'] else '未提供，不构成负项。'), '',
        '处理建议：' + cell(a['recommendation']), '',
        '## 格式检查', '',
        '| 编号 | 检查点 | 脚本状态 | 检查项分布 |', '| --- | --- | --- | --- |',
    ]
    for group in sorted(s['groups'], key=lambda g: g['id']):
        dist = {status: sum(c['group'] == group['id'] and c['status'] == status for c in s['checks']) for status in PRIORITY}
        lines.append('| ' + ' | '.join([group['id'], GROUPS[group['id']], group['status'],
                                       '、'.join(k + ' ' + str(v) for k, v in dist.items() if v)]) + ' |')
    lines += ['', '非通过项及覆盖限制（扫描线索需结合人工解释）：', '',
              '| 检查项 | 状态 | 证据 | 原因 |', '| --- | --- | --- | --- |']
    for c in s['checks']:
        if c['status'] != '通过':
            lines.append('| ' + ' | '.join([cell(c['id']), c['status'], evidence(c['evidence']), cell(c['reason'])]) + ' |')
    if a['format_notes']:
        lines += ['', '人工核对（保留工具原始状态，说明已消歧、已确认或仍待补证的范围）：', '',
                  '| 检查项 | 人工处置 | 证据与说明 |', '| --- | --- | --- |']
        for note in a['format_notes']:
            lines.append('| ' + ' | '.join([cell(note['check_id']), cell(note['disposition']), cell(note['reason']) + ' 证据：' + evidence(note['evidence'])]) + ' |')
    lines += ['', '## 内容质量（包质量 C1–C8）', '', '档位：0 核心不满足；1 明显缺口；2 基本达标；3 充分稳健；待核实表示证据不足。不计算总分，与题包自身的作答分数区分。', '',
              '| 编号 | 评价点 | 档位 | 证据 | 理由 | 建议 |', '| --- | --- | --- | --- | --- | --- |']
    for c in sorted(a['content'], key=lambda x: x['id']):
        lines.append('| ' + ' | '.join([c['id'], DIMENSIONS[c['id']], LEVELS[c['score']], evidence(c['evidence']), cell(c['reason']), cell(c['action'])]) + ' |')
    ref = a['reference_solution']
    if ref['provided']:
        lines += ['', '## 已提供的参考资料（可选）', '']
        for key, label in [('method', '参考方法'), ('known_result', '已有结果'), ('limitations', '已知限制或未核实范围')]:
            lines.append('- ' + label + '：' + cell(ref[key]))
        lines.append('- 证据：' + evidence(ref['evidence']))
    lines += ['', '## 需处理事项', '', '| 问题编号 | 具体问题 | 证据 | 修改、补证或确认要求 |', '| --- | --- | --- | --- |']
    for issue in a['issues']:
        lines.append('| ' + ' | '.join([cell(issue['id']), cell(issue['title']), evidence(issue['evidence']), cell(issue['action'])]) + ' |')
    if not a['issues']:
        lines.append('| — | 所查范围无新增处理事项 | 本报告覆盖范围 | 仍需按发布流程决策 |')
    lines += ['', '本次未执行镜像构建、任务脚本、参考解、评分器或实验。报告只提供审核结论与处理建议，不代表已获入库或公开授权。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['structure', 'assessment', 'output']:
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        structure = json.loads(Path(args.structure).read_text(encoding='utf-8'))
        assessment = json.loads(Path(args.assessment).read_text(encoding='utf-8'))
        validate(structure, assessment)
        output = Path(args.output).resolve()
        if inside(output, Path(structure['package_root']).resolve()):
            raise ValueError('输出必须位于源任务包之外')
        if output.exists() and not args.overwrite:
            raise ValueError('输出已存在；使用新文件或显式 --overwrite')
        report = render(structure, assessment)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('w' if args.overwrite else 'x', encoding='utf-8') as stream:
            stream.write(report)
        print(json.dumps({'output': str(output), 'content_dimensions': 8, 'reference_provided': assessment['reference_solution']['provided']}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print('报告生成失败：' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
