"""Conservative model output rules. Pure functions, no IO or model calls."""
import copy


def normalize_task(task, prior=None):
    q = copy.deepcopy(task)
    prior = prior or {}
    manual = prior.get('_user_state')
    if isinstance(manual, dict):
        q['status'] = manual.get('status', prior.get('status', 'active'))
        q.pop('completion_candidate', None)
    if not isinstance(manual, dict) and q.get('status') == 'done' and prior.get('status') != 'done':
        q['status'] = 'pending'
        q['completion_candidate'] = True
        q['live_progress'] = '疑似完成，待你确认'
        q['completion_evidence'] = str(q.get('completion_evidence') or q.get('note') or '')[:240]
        for field in ('completed_at', 'completedAt', 'done_at'):
            q.pop(field, None)
    if q.get('completion_candidate') and q.get('status') != 'done':
        q['status'] = 'pending'
    live = str(q.get('live_progress') or '').strip()
    if live:
        q['live_progress'] = live[:22]
    bounds = q.get('progress_range')
    basis = str(q.get('progress_basis') or '').strip()
    valid = (isinstance(bounds, list) and len(bounds) == 2 and
             all(type(v) in (int, float) for v in bounds) and
             0 <= bounds[0] <= bounds[1] <= 95 and bool(basis))
    if not valid:
        q.pop('progress_range', None)
        q.pop('progress_basis', None)
    else:
        q['progress_range'] = [int(bounds[0]), int(bounds[1])]
        q['progress_basis'] = basis[:180]
    if q.get('status') == 'waiting':
        for field in ('progress_range', 'progress_basis', 'progress_percent', 'estimated_progress'):
            if field in prior:
                q[field] = copy.deepcopy(prior[field])
            else:
                q.pop(field, None)
    return q
