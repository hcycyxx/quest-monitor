"""V6 shared state transactions. Standard library only; no network or workers."""
import copy
import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

KEYS = ('main_quests', 'side_quests')
TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


@contextmanager
def state_lock(path, timeout=8):
    lock = open(str(path) + '.lock', 'a+b')
    acquired = False
    try:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b'0')
            lock.flush()
        start = time.monotonic()
        while True:
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if time.monotonic() - start > timeout:
                    raise TimeoutError('任务正在保存，请稍后重试') from exc
                time.sleep(.04)
        yield
    finally:
        if acquired:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def read_state(path):
    try:
        with open(path, encoding='utf-8') as f:
            value = json.load(f)
    except FileNotFoundError:
        return {'main_quests': [], 'side_quests': []}
    if not isinstance(value, dict):
        raise ValueError('任务数据格式不正确，未覆盖原文件')
    return value


def _atomic_write(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(8):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(.05)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_state(path, state):
    """Full replacement for explicit callers; normal UI edits use mutate_state."""
    with state_lock(path):
        value = copy.deepcopy(state)
        value['updated_at'] = now()
        _atomic_write(path, value)


def mutate_state(path, change):
    with state_lock(path):
        state = read_state(path)
        change(state)
        state['updated_at'] = now()
        _atomic_write(path, state)
        return state


def user_toggle(path, key, qid, step=None):
    def edit(state):
        q = next((q for q in state.get(key, []) if q.get('id') == qid), None)
        if q is None:
            raise ValueError('任务已变化，请刷新后重试')
        steps = q.get('steps') or []
        manual = q.setdefault('_user_state', {'steps': {}})
        overrides = manual.setdefault('steps', {})
        if step is None:
            done = q.get('status') != 'done'
            q['status'] = 'done' if done else 'active'
            for s in steps:
                s['done'] = done
                overrides[str(s.get('text', '')).strip()] = done
        else:
            if not 0 <= step < len(steps):
                raise ValueError('步骤已变化，请刷新后重试')
            s = steps[step]
            s['done'] = not bool(s.get('done'))
            overrides[str(s.get('text', '')).strip()] = s['done']
            if all(x.get('done') for x in steps):
                q['status'] = 'done'
            elif q.get('status') == 'done':
                q['status'] = 'active'
        if q.get('status') == 'done':
            q.setdefault('completed_at', now())
        else:
            for field in ('completed_at', 'completedAt', 'done_at'):
                q.pop(field, None)
        manual['status'] = q.get('status', 'active')
        manual['changed_at'] = now()
    return mutate_state(path, edit)


def merge_ai_state(proposal, latest, max_active=8):
    """Merge with the latest disk state, never the stale pre-request snapshot."""
    result = {k: copy.deepcopy(v) for k, v in proposal.items() if k not in KEYS}
    for key in KEYS:
        old = [q for q in latest.get(key, []) if isinstance(q, dict)]
        exact = {(str(q.get('id', '')), str(q.get('title', ''))): q for q in old}
        by_id = {str(q.get('id', '')): q for q in old}
        output, used = [], set()
        for raw in proposal.get(key, []) if isinstance(proposal.get(key, []), list) else []:
            if not isinstance(raw, dict):
                continue
            q = copy.deepcopy(raw)
            q.pop('_user_state', None)
            ident = (str(q.get('id', '')), str(q.get('title', '')))
            prior = exact.get(ident)
            if prior is None and ident[0] in by_id:
                candidate = by_id[ident[0]]
                if candidate.get('status') != 'done':
                    prior = candidate
                else:
                    # A new title reusing a finished ID must not overwrite history.
                    q['id'] = ident[0] + '-' + hashlib.sha1(ident[1].encode()).hexdigest()[:6]
                    prior = exact.get((str(q['id']), ident[1]))
            q['steps'] = [s for s in q.get('steps', []) if isinstance(s, dict)] if isinstance(q.get('steps', []), list) else []
            if prior:
                used.add((str(prior.get('id', '')), str(prior.get('title', ''))))
                manual = prior.get('_user_state')
                if isinstance(manual, dict):
                    q['title'] = prior.get('title', q.get('title', ''))
                    q['_user_state'] = copy.deepcopy(manual)
                    q['status'] = manual.get('status', prior.get('status', 'active'))
                    overrides = manual.get('steps', {})
                    present = {str(s.get('text', '')).strip() for s in q['steps']}
                    q['steps'].extend(copy.deepcopy(s) for s in prior.get('steps', [])
                                      if str(s.get('text', '')).strip() in overrides and str(s.get('text', '')).strip() not in present)
                    for s in q['steps']:
                        text = str(s.get('text', '')).strip()
                        if text in overrides:
                            s['done'] = bool(overrides[text])
                else:
                    if prior.get('status') == 'done':
                        q = copy.deepcopy(prior)
                    previous_steps = {str(s.get('text', '')).strip(): s.get('done') for s in prior.get('steps', [])}
                    for s in q['steps']:
                        if previous_steps.get(str(s.get('text', '')).strip()):
                            s['done'] = True
                if q.get('status') == 'done':
                    for field in ('completed_at', 'completedAt', 'done_at'):
                        if prior.get(field):
                            q[field] = prior[field]
                else:
                    for field in ('completed_at', 'completedAt', 'done_at'):
                        q.pop(field, None)
            output.append(q)
        # The model's abbreviated response is never an instruction to delete history
        # or a task that the user has explicitly edited.
        for q in old:
            ident = (str(q.get('id', '')), str(q.get('title', '')))
            if ident not in used and (q.get('status') == 'done' or q.get('_user_state')):
                output.append(copy.deepcopy(q))
        kept, ordinary = [], 0
        seen = set()
        for q in output:
            ident = (str(q.get('id', '')), str(q.get('title', '')))
            if ident in seen:
                continue
            seen.add(ident)
            if q.get('status') == 'done' or q.get('_user_state'):
                kept.append(q)
            elif ordinary < max_active:
                ordinary += 1
                q['steps'] = q.get('steps', [])[:10]
                kept.append(q)
        result[key] = kept
    return result


def apply_ai_update(path, proposal):
    with state_lock(path):
        latest = read_state(path)
        merged = merge_ai_state(proposal, latest)
        signature = lambda s: json.dumps({k: v for k, v in s.items() if k != 'updated_at'}, ensure_ascii=False, sort_keys=True)
        changed = signature(latest) != signature(merged)
        if changed:
            merged['updated_at'] = now()
            _atomic_write(path, merged)
        return changed, merged
