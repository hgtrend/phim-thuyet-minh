"""Hàm dùng chung cho dây chuyền «phim thuyết minh» (bản chạy trên máy khách, chuyển từ dây chuyền một kênh của HG Studio).

Không khoá, không đường dẫn riêng của máy nào. Mọi việc cần model hay dịch vụ trả tiền (dịch, đọc giọng, nhạc, tải video Douyin) do TRỢ LÝ AI của
người dùng làm — bằng kỹ năng «lam-video-thuyet-minh» của gói HG Trend. Máy chỉ làm phần xử lý tại chỗ (tách tiếng, nghe chữ, làm mờ, dựng).

Chỗ cần trợ lý: bước ghi một PHIẾU (tệp CAN_*.json trong thư mục tập) rồi thoát mã 3 — trợ lý làm theo phiếu, xong chạy lại đúng bước đó.
"""
import json, math, os, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from urllib.parse import urlsplit

GOC_GOI = Path(__file__).resolve().parent.parent          # thư mục kho mã
PHONG = GOC_GOI / "phong"                                 # phông chữ đi kèm (Baloo 2 — SIL Open Font License 1.1)
FONT_SUB = str(PHONG / "Baloo2-ExtraBold.ttf")
FONT_BIA = str(PHONG / "Baloo2-ExtraBold.ttf")
CHO_TRO_LY = 3                                            # mã thoát: phiếu đã ghi, chờ trợ lý làm rồi chạy lại bước

# Bộ số chất lượng — đo trên một kênh thuyết minh của HG Studio (09/2026). Người dùng đổi được bằng tệp cau_hinh.json trong thư mục gốc dự án.
CAU_HINH_GOC = {
    "tieng_goc_volume": 0.50,     # tiếng + hiệu ứng gốc (đã bỏ nhạc)
    "giong_viet_volume": 1.25,    # giọng thuyết minh
    "nhac_volume": 0.20,          # nhạc nền, còn bị nén thêm khi có giọng
    "toc_do_giong": 1.20,         # giọng CapCut từ HG Trend đọc 1,0× ⇒ máy tăng tốc 1,2× (kênh gốc đo ở 1,2×)
    "tu_moi_giay": 5.0,           # đo trên giọng CapCut 1,2×: 4,7–5,5 từ/giây — đổi giọng / tốc độ thì đo lại
    "atempo_max": 1.10,           # nén thêm tối đa +10% để vừa khe
    "atempo_cung": 1.18,          # trần cứng khi đã rút gọn lời mà vẫn dài
    "tran_giay": 0.60,            # giọng được tràn vào khoảng lặng sau câu tối đa 0,6 s
    "lufs": -14.0,                # chuẩn YouTube
    "sub_mau": "#FFF200",
    "sub_vien": "#000000",
    "sub_vien_px": 5,
    "sub_ty_le_chu": 0.048,       # cỡ chữ = 4,8% chiều cao khung
    "sub_rong_toi_da": 0.86,
    "sub_day": 0.955,             # đáy chữ ở 95,5% chiều cao
    "mo_ban_kinh": 16,            # bán kính làm mờ vùng chữ Trung
    "do_logo": True,              # dò logo / chữ ký kênh nguồn bằng nét đứng yên sát mép khung (B5) — dò nhầm thì đặt false
}

BUOC = ["b0_do_trung", "b1_nhan_nguon", "b2_tach_tieng", "b3_nghe", "b4_giong", "b5_mo_chu", "b6_nhac", "b7_dung", "b8_bia", "kiem"]
CJK = re.compile(r"[一-鿿㐀-䶿]")


def goc_du_an():
    """Thư mục chứa các tập: biến PTM_GOC, không có thì ./tap (theo thư mục đang đứng)."""
    return Path(os.environ.get("PTM_GOC") or (Path.cwd() / "tap")).resolve()


def cau_hinh():
    c = dict(CAU_HINH_GOC)
    f = goc_du_an() / "cau_hinh.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("phải là một đối tượng {…}")
            c.update(d)
        except (OSError, ValueError) as e:           # tệp cấu hình hỏng không được làm sập cả lệnh --help
            print(f"🟡 {f} không dùng được ({e}) — dùng bộ số mặc định", file=sys.stderr)
    return c


CAU_HINH = cau_hinh()


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def can(ten):
    """Đường dẫn chương trình bắt buộc (ffmpeg, ffprobe…) — thiếu thì dừng với câu hướng dẫn cài."""
    p = shutil.which(ten)
    if not p:
        sys.exit(f"🔴 Thiếu chương trình «{ten}». Cài: macOS «brew install {ten}», Ubuntu «sudo apt install {ten}».")
    return p


def chay(cmd, im=False, **kw):
    """Chạy lệnh, in lệnh rút gọn, ném lỗi nếu hỏng (không nuốt lỗi)."""
    if not im:
        s = " ".join(str(c) for c in cmd)
        log("$ " + (s if len(s) < 300 else s[:300] + " …"))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def ffprobe_dur(f):
    o = subprocess.check_output([can("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).decode().strip()
    return float(o)


def ffprobe_video(f):
    try:                                             # video hỏng / không có luồng hình ⇒ báo rõ, không văng lỗi thô
        o = subprocess.check_output([can("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                                     "stream=width,height,r_frame_rate,codec_name:stream_tags=rotate:stream_side_data=rotation", "-of", "json", str(f)]).decode()
        s = json.loads(o)["streams"][0]
        xoay = 0                                     # video quay điện thoại hay mang thẻ xoay: kích thước luồng chưa xoay
        for sd in s.get("side_data_list") or []:
            if "rotation" in sd:
                xoay = int(float(sd["rotation"]))
        xoay = xoay or int(float((s.get("tags") or {}).get("rotate") or 0))
        a, _, b = str(s.get("r_frame_rate") or "0/1").partition("/")
        fps = round(float(a) / float(b or 1), 3) if float(b or 1) else 0.0
        return {"w": int(s["width"]), "h": int(s["height"]), "fps": fps, "dur": ffprobe_dur(f), "codec": s.get("codec_name"), "xoay": xoay % 360}
    except (IndexError, KeyError, ValueError, ZeroDivisionError, subprocess.CalledProcessError, OSError):
        sys.exit(f"🔴 {f}: không đọc được luồng hình (tệp hỏng hoặc không phải video)")


def thiet_bi():
    """cuda (card Nvidia) → mps (Mac Apple Silicon) → cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def tap_dir(slug):
    if not re.fullmatch(r"[0-9A-Za-z_\-]{1,80}", slug or ""):
        sys.exit("🔴 Tên tập (--tap) chỉ dùng chữ không dấu, số, _ và -, vd T01_ten_bo")
    d = goc_du_an() / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def doc_tap(slug):
    f = tap_dir(slug) / "tap.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"tap": slug, "buoc": {}}


def ghi_tap(slug, **k):
    d = doc_tap(slug)
    for kk, v in k.items():
        if kk == "buoc":
            d.setdefault("buoc", {}).update(v)
        else:
            d[kk] = v
    d["cap_nhat"] = time.strftime("%Y-%m-%d %H:%M")
    (tap_dir(slug) / "tap.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def xong_buoc(slug, buoc, **thong_tin):
    thong_tin["luc"] = time.strftime("%Y-%m-%d %H:%M")
    ghi_tap(slug, buoc={buoc: thong_tin})


def doc_json(p, mac_dinh=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else mac_dinh


def ghi_json(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def cho_tro_ly(phieu, viec, **them):
    """Ghi phiếu cho trợ lý (CAN_*.json), in một dòng dặn, thoát mã 3."""
    ghi_json(phieu, {"viec": viec, "luc": time.strftime("%Y-%m-%d %H:%M"), **them})
    log(f"⏸ CHỜ TRỢ LÝ: {viec} — phiếu {phieu}")
    sys.exit(CHO_TRO_LY)


def nghe_chu(wav, ngon_ngu="zh", loi_nhac=None):
    """Nghe ra chữ có mốc giờ → [{start, end, text}]. Mac Apple Silicon có mlx-whisper thì dùng (nhanh), không thì faster-whisper (cuda / cpu)."""
    model = os.environ.get("PTM_WHISPER", "large-v3-turbo")
    try:
        import mlx_whisper
        r = mlx_whisper.transcribe(str(wav), language=ngon_ngu, path_or_hf_repo=f"mlx-community/whisper-{model}", initial_prompt=loi_nhac,
                                   condition_on_previous_text=False, word_timestamps=False)
        return [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in r["segments"]]
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("🔴 Thiếu bộ nghe chữ: «pip install faster-whisper» (Mac Apple Silicon có thể cài «pip install mlx-whisper»).")
    tb = thiet_bi()
    m = WhisperModel(model, device="cuda" if tb == "cuda" else "cpu", compute_type="float16" if tb == "cuda" else "int8")
    segs, _ = m.transcribe(str(wav), language=ngon_ngu, initial_prompt=loi_nhac, condition_on_previous_text=False, vad_filter=False)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]


def doc_tsv(f):
    """cau.tsv: # id  start  end  vi  (zh) — dòng # là chú thích."""
    hang = []
    for so, l in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
        if not l.strip() or l.startswith("#"):
            continue
        p = l.split("\t")
        try:                                         # dòng sai dạng (lời có xuống dòng, thiếu cột) ⇒ báo đúng dòng, không văng lỗi thô
            if len(p) < 3 or len(p) > 5 or int(p[0]) < 1:   # > 5 cột: lời có ký tự TAB
                raise ValueError
            bd, kt = float(p[1]), float(p[2])
            if not (math.isfinite(bd) and math.isfinite(kt) and 0 <= bd < kt):
                raise ValueError
            hang.append({"id": int(p[0]), "start": float(p[1]), "end": float(p[2]), "vi": p[3].strip() if len(p) > 3 else "",
                         "zh": p[4].strip() if len(p) > 4 else ""})
        except ValueError:
            sys.exit(f"🔴 {f} dòng {so} sai dạng: cần «id<TAB>start<TAB>end<TAB>lời Việt<TAB>chữ gốc» (0 ≤ start < end, lời không chứa TAB), mỗi câu một dòng — sửa dòng đó rồi chạy lại.")
    return hang


def ghi_tsv(f, cau):
    dong = ["# id\tstart\tend\tvi\t(zh — chữ gốc, chỉ để xem)"]
    for c in cau:
        dong.append(f"{c['id']}\t{c['start']:.2f}\t{c['end']:.2f}\t{(c.get('vi') or '').replace(chr(9), ' ')}\t{(c.get('zh') or '').replace(chr(9), ' ')}")
    Path(f).write_text("\n".join(dong) + "\n", encoding="utf-8")


def doc_cau(d):
    """Câu của tập: 03_dich/cau.json (đủ trường) với cột vi của 03_dich/cau.tsv đè lên (tsv là chỗ người / trợ lý sửa lời).
    Thiếu cau.json thì dựng từ tsv. Trả (danh_sach_cau, so_cau_doi_loi)."""
    d = Path(d)
    js, tsv = d / "03_dich/cau.json", d / "03_dich/cau.tsv"
    cau = doc_json(js) or []
    if not tsv.exists():
        return cau, 0
    hang = {h["id"]: h for h in doc_tsv(tsv)}
    if not cau:
        return list(hang.values()), 0
    doi = 0
    for c in cau:
        h = hang.get(c["id"])
        if h and h["vi"] != (c.get("vi") or ""):
            c["vi"] = h["vi"]; doi += 1
        if c.get("vi") is not None:
            c["so_tu"] = len(c["vi"].split())       # lời đổi (rút gọn) thì số từ đổi theo
    return cau, doi


def la_link_web(u):
    """Chỉ nhận link http(s) — chặn file:// và đường dẫn cục bộ trong tệp kết quả do trợ lý lưu (không đọc tệp riêng trên máy)."""
    try:
        p = urlsplit(str(u))
        return p.scheme in ("http", "https") and bool(p.hostname)
    except ValueError:
        return False


# Bộ mở link CHỈ http/https, kể cả khi bị chuyển hướng (không có bộ đọc file://, ftp://, data:) — mọi bước tải đều đi qua đây.
_MO_WEB = urllib.request.OpenerDirector()
for _h in (urllib.request.ProxyHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), urllib.request.HTTPRedirectHandler(),
           urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
    _MO_WEB.add_handler(_h)


UA_MAC_DINH = "phim-thuyet-minh/1.0 (+https://github.com/hgtrend/phim-thuyet-minh)"


def mo_web(url, headers=None, timeout=60):
    """Mở một link http(s) an toàn; link hay đích chuyển hướng không phải http(s) ⇒ ValueError."""
    if not la_link_web(url):
        raise ValueError(f"không phải link http(s): {str(url)[:80]}")
    h = dict(headers or {})
    h.setdefault("User-Agent", UA_MAC_DINH)   # 26/11: tường chống bot Cloudflare chặn tên mặc định «Python-urllib» (403) ở link tệp giọng hgtrend.com/am/
    r = _MO_WEB.open(urllib.request.Request(url, headers=h), timeout=timeout)
    if not la_link_web(r.geturl()):
        r.close()
        raise ValueError(f"bị chuyển sang link không phải http(s): {r.geturl()[:80]}")
    return r
