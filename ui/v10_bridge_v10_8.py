"""Card order is a display preference, not a task/priority mutation."""
import copy
from v10_bridge_v10_5 import Bridge as PreviousBridge,ROOT
from v10_bridge_v10_3 import read_json


class Bridge(PreviousBridge):
    @staticmethod
    def _card_order(value):
        if not isinstance(value,list) or len(value)>2000:raise ValueError('卡片顺序格式不正确')
        result=[];seen=set()
        for key in value:
            if not isinstance(key,str) or len(key)>250 or not key.startswith(('main_quests:','side_quests:')):
                raise ValueError('卡片标识不正确')
            if key not in seen:result.append(key);seen.add(key)
        return result

    def __init__(self,data_dir=None,controller=None):
        super().__init__(data_dir,controller)
        try:self._prefs['cardOrder']=self._card_order(read_json(self._prefs_path,{}).get('cardOrder',[]))
        except ValueError:self._prefs['cardOrder']=[]

    def preferences(self,patch):
        if not isinstance(patch,dict) or 'cardOrder' not in patch:return super().preferences(patch)
        with self._lock:
            old=copy.deepcopy(self._prefs)
            try:
                self._prefs['cardOrder']=self._card_order(patch['cardOrder'])
                result=super().preferences({key:value for key,value in patch.items() if key!='cardOrder'})
                if not result.get('ok'):self._prefs=old
                return result
            except (ValueError,OSError) as exc:
                self._prefs=old
                return {'ok':False,'error':'卡片顺序未保存：'+str(exc)}
