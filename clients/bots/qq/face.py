import hashlib
import json
import os
import re

from clients.bots.qq.utils import EMOTION_LABEL_NORMALIZATION


class QQFaceInjector:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
        )
        self._prefs = self._load_prefs()
        self._avoid_face_ids = set((self._prefs.get("qq") or {}).get("avoid_face_ids") or [])
        self._smile_face_ids = [
            int(x)
            for x in ((self._prefs.get("qq") or {}).get("smile_face_ids") or [])
            if str(x).strip().isdigit()
        ]
        self._label_aliases = (self._prefs.get("qq") or {}).get("label_aliases") or {}
        self._prefer_kaomoji_labels = set(
            (self._prefs.get("qq") or {}).get("prefer_kaomoji_labels") or []
        )
        self._prefer_face_labels = set(
            (self._prefs.get("qq") or {}).get("prefer_face_labels") or []
        )
        self._allow_kaomoji = bool(
            (self._prefs.get("qq") or {}).get("enable_kaomoji", False)
        )
        try:
            self._kaomoji_probability = float(
                (self._prefs.get("qq") or {}).get("kaomoji_probability", 0.42)
            )
        except Exception:
            self._kaomoji_probability = 0.42
        if self._kaomoji_probability < 0.0:
            self._kaomoji_probability = 0.0
        if self._kaomoji_probability > 1.0:
            self._kaomoji_probability = 1.0
        self._sysface_id_set = self._load_sysface_id_set()
        self._qq_code_to_id = self._load_face_code_map()
        self._kaomoji_lib = self._load_kaomoji_lib()
        self._recent_picks = {}
        self._recent_limit = 6

        # 映射中文标签到颜文字库的英文 tag
        self._tag_mapping = {
            "微笑": ["smiling", "happy"],
            "开心": ["smiling", "happy", "excited"],
            "笑": ["smiling", "happy"],
            "大笑": ["smiling", "happy"],
            "呲牙": ["smiling", "happy"],
            "害羞": ["blush", "shy"],
            "羞涩": ["blush", "shy"],
            "脸红": ["blush"],
            "捂脸": ["blush", "shy"],
            "托腮": ["smiling", "blush"],
            "亲亲": ["kiss"],
            "飞吻": ["kiss"],
            "啵啵": ["kiss"],
            "爱你": ["heart", "love"],
            "比心": ["heart", "love"],
            "爱心": ["heart", "love"],
            "抱抱": ["hug"],
            "拥抱": ["hug"],
            "哭": ["crying", "sad"],
            "大哭": ["crying", "sad"],
            "流泪": ["crying", "sad"],
            "委屈": ["sad", "sweat"],
            "难过": ["sad"],
            "生气": ["anger"],
            "发怒": ["anger"],
            "惊恐": ["surprised", "shock"],
            "惊讶": ["surprised"],
            "调皮": ["wink"],
            "眨眼": ["wink"],
            "睡": ["asleep"],
            "困": ["asleep"],
            "加油": ["flex", "excited"],
            "赞": ["thumbs_up"],
            "狗": ["dog"],
            "猫": ["cat"],
            "熊": ["bear"],
            "卖萌": ["blush", "smiling", "cat"],
            "焦虑": ["anxious", "sad", "sweat"],
            "紧张": ["anxious", "sweat"],
            "疑问": ["question", "confused"],
            "中性": ["neutral", "smiling"],
            "冷淡": ["neutral"],
            "傲娇": ["smirk", "blush"],
            "委屈巴巴": ["sad", "blush"],
        }

        self._label_to_id = {
            "微笑": 21,
            "撇嘴": 1,
            "色": 2,
            "发呆": 3,
            "得意": 4,
            "流泪": 5,
            "害羞": 6,
            "闭嘴": 7,
            "睡": 8,
            "大哭": 9,
            "尴尬": 10,
            "发怒": 11,
            "调皮": 12,
            "呲牙": 13,
            "难过": 15,
            "酷": 16,
            "抓狂": 18,
            "吐": 19,
            "偷笑": 20,
            "可爱": 21,
            "白眼": 22,
            "傲慢": 23,
            "饥饿": 24,
            "困": 25,
            "惊恐": 26,
            "流汗": 27,
            "憨笑": 28,
            "大兵": 29,
            "奋斗": 30,
            "咒骂": 31,
            "疑问": 32,
            "嘘": 33,
            "晕": 34,
            "折磨": 35,
            "衰": 36,
            "骷髅": 37,
            "敲打": 38,
            "再见": 39,
            "擦汗": 40,
            "抠鼻": 41,
            "鼓掌": 42,
            "糗大了": 43,
            "坏笑": 44,
            "左哼哼": 45,
            "右哼哼": 46,
            "哈欠": 47,
            "鄙视": 48,
            "委屈": 49,
            "快哭了": 50,
            "阴险": 51,
            "亲亲": 52,
            "吓": 53,
            "可怜": 54,
            "菜刀": 55,
            "西瓜": 56,
            "啤酒": 57,
            "篮球": 58,
            "乒乓": 59,
            "咖啡": 60,
            "饭": 61,
            "猪头": 62,
            "玫瑰": 63,
            "凋谢": 64,
            "示爱": 65,
            "爱心": 66,
            "心碎": 67,
            "蛋糕": 68,
            "闪电": 69,
            "炸弹": 70,
            "刀": 71,
            "足球": 72,
            "瓢虫": 73,
            "便便": 74,
            "月亮": 75,
            "太阳": 76,
            "礼物": 77,
            "拥抱": 78,
            "强": 79,
            "弱": 80,
            "握手": 81,
            "胜利": 82,
            "抱拳": 83,
            "勾引": 84,
            "拳头": 85,
            "差劲": 86,
            "爱你": 87,
            "NO": 88,
            "OK": 89,
            "爱情": 90,
            "飞吻": 91,
            "跳跳": 92,
            "发抖": 93,
            "怄火": 94,
            "转圈": 95,
            "磕头": 96,
            "回头": 97,
            "跳绳": 98,
            "挥手": 99,
            "激动": 100,
            "街舞": 101,
            "献吻": 102,
            "左太极": 103,
            "右太极": 104,
            "笑": 21,
            "哭": 5,
            "生气": 11,
        }
        self._id_to_label = {v: k for k, v in self._label_to_id.items()}
        self._id_to_label[14] = "微笑"

        self._allowed_face_ids = set(self._sysface_id_set) if self._sysface_id_set else set(self._id_to_label.keys())
        if self._smile_face_ids:
            self._smile_face_ids = [x for x in self._smile_face_ids if x in self._allowed_face_ids]

        self._label_re = re.compile(r"[\[【]([^\]】\s:：]{1,10})[\]】]")
        self._slash_code_re = re.compile(r"/[A-Za-z0-9_]{1,24}|/[\u4e00-\u9fa5]{1,10}")

        self._ascii_replacements = [
            (re.compile(r"(?<!:)\:-\)"), "__smile__"),
            (re.compile(r"(?<!:)\:\)"), "__smile__"),
            (re.compile(r"\:-D"), 13),
            (re.compile(r"\:D"), 13),
            (re.compile(r"(?<!:)\:-\("), 5),
            (re.compile(r"(?<!:)\:\("), 5),
        ]

        self._label_normalization = dict(EMOTION_LABEL_NORMALIZATION)
    def _load_prefs(self):
        path = os.path.join(self._project_root, "external", "emoji_libs", "qq_emoji_preference.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _load_sysface_id_set(self):
        path = os.path.join(
            self._project_root,
            "external",
            "NapCatQQ-main",
            "packages",
            "napcat-core",
            "external",
            "face_config.json",
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return set()

        sysface = data.get("sysface")
        if not isinstance(sysface, list):
            return set()

        out = set()
        for it in sysface:
            if not isinstance(it, dict):
                continue
            sid = it.get("QSid")
            if isinstance(sid, int):
                out.add(sid)
            elif isinstance(sid, str) and sid.isdigit():
                out.add(int(sid))
        return out

    def _load_kaomoji_lib(self):
        path = os.path.join(self._project_root, "external", "emoji_libs", "kaomoji_library.json")
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _load_face_code_map(self):
        path = os.path.join(
            self._project_root,
            "external",
            "NapCatQQ-main",
            "packages",
            "napcat-core",
            "external",
            "face_config.json",
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}

        out = {}

        def _collect(arr):
            if not isinstance(arr, list):
                return
            for it in arr:
                if not isinstance(it, dict):
                    continue
                code = it.get("QDes")
                sid = it.get("QSid")
                if not isinstance(code, str) or not code.startswith("/"):
                    continue
                if isinstance(sid, int):
                    out[code] = sid
                elif isinstance(sid, str) and sid.isdigit():
                    out[code] = int(sid)

        _collect(data.get("sysface"))
        return out

    def _stable_pick(self, key: str, text: str, candidates):
        if not candidates:
            return None
        s = (key + "|" + (text or "")).encode("utf-8")
        h = hashlib.md5(s).hexdigest()
        idx = int(h[:8], 16) % len(candidates)
        return candidates[idx]

    def _stable_index(self, key: str, text: str, n: int) -> int:
        if n <= 0:
            return 0
        s = (key + "|" + (text or "")).encode("utf-8")
        h = hashlib.md5(s).hexdigest()
        return int(h[:8], 16) % n

    def _remember_pick(self, key: str, picked):
        if key not in self._recent_picks:
            self._recent_picks[key] = []
        arr = self._recent_picks[key]
        arr.append(picked)
        if len(arr) > int(self._recent_limit or 0):
            del arr[: len(arr) - int(self._recent_limit or 0)]

    def _pick_avoiding_recent(self, key: str, text: str, candidates):
        if not candidates:
            return None
        recent = self._recent_picks.get(key, [])
        base = self._stable_index(key, text, len(candidates))
        for step in range(len(candidates)):
            cand = candidates[(base + step) % len(candidates)]
            if cand in recent:
                continue
            self._remember_pick(key, cand)
            return cand
        cand = candidates[base]
        self._remember_pick(key, cand)
        return cand

    def _key_with_scope(self, scope: str, key: str) -> str:
        scope = str(scope or "").strip()
        return f"{scope}|{key}" if scope else key

    def _normalize_face_id(self, face_id, text: str, scope: str):
        if face_id == "__smile__":
            if self._smile_face_ids:
                picked = self._pick_avoiding_recent(
                    self._key_with_scope(scope, "face___smile__"),
                    text,
                    self._smile_face_ids,
                )
                if picked is not None and picked not in self._avoid_face_ids:
                    return int(picked)
            return None

        if isinstance(face_id, int):
            if face_id not in self._allowed_face_ids:
                return None
            return None if face_id in self._avoid_face_ids else face_id
        if isinstance(face_id, str) and face_id.isdigit():
            v = int(face_id)
            if v not in self._allowed_face_ids:
                return None
            return None if v in self._avoid_face_ids else v
        return None

    def _pick_kaomoji(self, label: str, text: str, scope: str) -> str:
        tags = self._tag_mapping.get(label, [])
        if not tags:
            n_label = self._label_normalization.get(label, label)
            tags = self._tag_mapping.get(n_label, [])
        candidates = []
        for tag in tags:
            v = self._kaomoji_lib.get(tag, [])
            if isinstance(v, list):
                candidates.extend(v)

        if not candidates:
            generic_tags = ["smiling", "neutral", "happy"]
            if label in {"生气", "发怒", "愤怒", "暴躁"}:
                generic_tags = ["anger", "smirk"]
            elif label in {"疑问", "疑惑", "困惑"}:
                generic_tags = ["question", "confused", "neutral"]
            elif label in {"难过", "委屈", "伤心", "失落", "低落"}:
                generic_tags = ["sad", "sweat", "blush"]
            elif label in {"困", "睡", "困倦", "疲惫"}:
                generic_tags = ["asleep", "tired"]
            for tag in generic_tags:
                v = self._kaomoji_lib.get(tag, [])
                if isinstance(v, list):
                    candidates.extend(v)

        if not candidates and self._kaomoji_lib:
            v = self._kaomoji_lib.get("smiling", [])
            if isinstance(v, list):
                candidates.extend(v)

        if candidates:
            picked = self._pick_avoiding_recent(
                self._key_with_scope(scope, f"kao_{label}"),
                text,
                candidates,
            )
            return picked or ""
        return ""

    def _pick_for_label(self, label: str, text: str, scope: str):
        label = self._label_normalization.get(label, label)
        alias_list = self._label_aliases.get(label)
        candidates = []

        if isinstance(alias_list, list):
            for a in alias_list:
                if a == "__smile__":
                    candidates.extend([x for x in self._smile_face_ids if x not in self._avoid_face_ids])
                    continue
                if isinstance(a, str):
                    code = a if a.startswith("/") else ("/" + a)
                    fid = self._qq_code_to_id.get(code)
                if isinstance(fid, int) and fid in self._allowed_face_ids and fid not in self._avoid_face_ids:
                    candidates.append(fid)
            picked = self._pick_avoiding_recent(
                self._key_with_scope(scope, f"face_{label}"),
                text,
                candidates,
            )
            if picked is not None:
                return int(picked)

        face_id = self._label_to_id.get(label)
        fid = self._normalize_face_id(face_id, text, scope)
        if fid is not None:
            if label in {"微笑", "笑"} and self._smile_face_ids:
                picked = self._pick_avoiding_recent(
                    self._key_with_scope(scope, "face___smile__"),
                    text,
                    [x for x in self._smile_face_ids if x not in self._avoid_face_ids],
                )
                return int(picked) if picked is not None else int(fid)
            return int(fid)

        code_fid = self._qq_code_to_id.get("/" + label)
        if isinstance(code_fid, int) and code_fid not in self._avoid_face_ids:
            return int(code_fid)

        if label in {"微笑", "笑"} and self._smile_face_ids:
            picked = self._pick_avoiding_recent(
                self._key_with_scope(scope, "face___smile__"),
                text,
                [x for x in self._smile_face_ids if x not in self._avoid_face_ids],
            )
            return int(picked) if picked is not None else None

        return None

    def apply(self, text, scope: str = ""):
        if not self.enabled:
            return text
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)

        scope = str(scope or "").strip()

        def _slash_repl(m: re.Match):
            code = m.group(0)
            if not code:
                return code
            if m.start() > 0 and text[m.start() - 1] == ":":
                return code
            fid = self._qq_code_to_id.get(code)
            if isinstance(fid, int):
                if fid in self._avoid_face_ids or fid not in self._allowed_face_ids:
                    picked = self._pick_avoiding_recent(
                        self._key_with_scope(scope, "face___smile__"),
                        text,
                        [x for x in self._smile_face_ids if x not in self._avoid_face_ids],
                    )
                    return f"[CQ:face,id={int(picked)}]" if picked is not None else code
                return f"[CQ:face,id={fid}]"
            return code

        text = self._slash_code_re.sub(_slash_repl, text)

        def _label_repl(m: re.Match):
            label = m.group(1)
            if not label:
                return m.group(0)

            label = str(label).strip()
            label = self._label_normalization.get(label, label)

            if self._allow_kaomoji and label in self._prefer_kaomoji_labels:
                kao = self._pick_kaomoji(label, text, scope)
                if kao:
                    return kao
            if label in self._prefer_face_labels:
                fid = self._pick_for_label(label, text, scope)
                if fid:
                    return f"[CQ:face,id={fid}]"

            use_kaomoji = False
            if self._allow_kaomoji:
                if self._kaomoji_probability >= 1.0:
                    use_kaomoji = True
                elif self._kaomoji_probability > 0:
                    threshold = int(round(self._kaomoji_probability * 100))
                    gate = int(hashlib.md5(f"choice_{label}|{text}".encode("utf-8")).hexdigest()[:6], 16) % 100
                    use_kaomoji = gate < threshold

            if self._allow_kaomoji and use_kaomoji:
                kao = self._pick_kaomoji(label, text, scope)
                if kao:
                    return kao

            fid = self._pick_for_label(label, text, scope)
            if not fid:
                if self._allow_kaomoji:
                    kao = self._pick_kaomoji(label, text, scope)
                    if kao:
                        return kao
                return m.group(0)

            return f"[CQ:face,id={fid}]"

        text = self._label_re.sub(_label_repl, text)

        for pattern, face_id in self._ascii_replacements:
            fid = self._normalize_face_id(face_id, text, scope)
            if fid is None:
                continue
            text = pattern.sub(f"[CQ:face,id={fid}]", text)

        return text

    def extract(self, text):
        if not self.enabled:
            return text
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        if "[CQ:face,id=" not in text:
            return text

        def _face_repl(m: re.Match):
            try:
                face_id = int(m.group(1))
                label = self._id_to_label.get(face_id)
                if label:
                    return f"[{label}]"
                return ""
            except Exception:
                return m.group(0)

        return re.sub(r"\[CQ:face,id=(\d+)\]", _face_repl, text)

