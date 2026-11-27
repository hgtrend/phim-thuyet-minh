"""B4 — GIỌNG VIỆT: mỗi câu một tệp `04_giong/raw/cau_NNN.mp3` (món HG Trend «Đọc lời bằng giọng CapCut», tốc độ 1,0×),
máy tăng tốc ×toc_do_giong (1,2), cắt lặng, khớp vào khe thời gian của câu gốc, ghép `04_giong/giong_viet.wav` (48 kHz mono).

Khe = từ start tới min(start câu sau − 0,12 s, end + 0,6 s). Giọng dài hơn khe ⇒ nén atempo tối đa 1,10; vẫn dài ⇒ phiếu
CAN_RUT_GON.json (trợ lý viết câu ngắn hơn trong cau.tsv, câu đổi lời được đọc lại); còn dài nữa ⇒ mượn khe câu sau, nén tới trần
cứng 1,18 (khe < 1,2 s: 1,30). KHÔNG kéo chậm giọng cho vừa khe.

Câu nào đổi lời (md5 cột vi) hoặc thiếu mp3 ⇒ phiếu CAN_DOC.json (lô ≤ 60 câu / 6.000 ký tự), thoát mã 3.

    python -m ptm.b4_giong --tap <slug> [--giong nu-de-thuong] [--doc-lai] [--khong-rut-gon]
    python -m ptm.b4_giong --tap <slug> --nhan ket_qua_lo1.json [--lo 1]     # tải mp3 từ kết quả món HG Trend rồi chạy tiếp
"""
import argparse, hashlib, json, math, subprocess, sys, time
from pathlib import Path

from .chung import CAU_HINH, CHO_TRO_LY, can, chay, cho_tro_ly, doc_cau, doc_json, doc_tap, ffprobe_dur, ghi_json, la_link_web, log, mo_web, tap_dir, \
    xong_buoc

LO_CAU, LO_KY_TU = 60, 6000          # giới hạn một lần gọi món «Đọc lời bằng giọng CapCut»
TRAN_MP3 = 30 * 1024 * 1024          # một câu mp3 tải về tối đa 30 MB
LO_TRON = 100                        # mỗi lượt ffmpeg trộn ≤ 100 tệp (macOS mặc định chỉ mở 256 tệp / tiến trình)
CONG_CU_GIONG = "Đọc lời bằng giọng CapCut (hggiong)"


def tag(c):
    return f"cau_{c['id']:03d}"


def bam(s):
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()[:10]


def md5_tep(p):
    p = Path(p)
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None


def la_mp3(p):
    """Tệp tiếng đọc được (ffprobe ra luồng audio, dài > 0,1 s)."""
    try:
        o = subprocess.run([can("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name:format=duration",
                            "-of", "json", str(p)], capture_output=True, text=True, check=True).stdout
        j = json.loads(o)
        return bool(j.get("streams")) and float(j.get("format", {}).get("duration") or 0) > 0.1
    except (subprocess.CalledProcessError, ValueError):
        return False


def chia_lo(viec):
    """[(id, vi)] → các lô ≤ 60 câu và ≤ 6.000 ký tự."""
    lo, cur, ky = [], [], 0
    for i, vi in viec:
        if cur and (len(cur) >= LO_CAU or ky + len(vi) > LO_KY_TU):
            lo.append(cur); cur, ky = [], 0
        cur.append((i, vi)); ky += len(vi)
    if cur:
        lo.append(cur)
    return lo


def nhan_phieu_cu(g, raw, cau_theo_id, cache):
    """Phiếu CAN_DOC cũ: tệp mp3 mới (khác md5 lúc ghi phiếu, hoặc ghi sau phiếu) và lời không đổi ⇒ nhận vào cache."""
    p = doc_json(g / "CAN_DOC.json")
    if not p:
        return 0
    n, ts = 0, float(p.get("ts") or 0)
    for lo in p.get("lo", []):
        for x in lo["cau"]:
            c = cau_theo_id.get(x["id"])
            f = raw / f"cau_{x['id']:03d}.mp3"
            if c and c.get("vi") == x["vi"] and f.exists() and (md5_tep(f) != x.get("md5_cu") or f.stat().st_mtime > ts) and la_mp3(f):
                cache[tag(c)] = bam(x["vi"]); n += 1
    return n


def tai_ve(link, dich):
    """Tải link về `dich` theo từng khúc, quá TRAN_MP3 thì bỏ; ghi ra <tên>.part rồi mới đổi tên."""
    part = dich.with_name(dich.name + ".part")
    n = 0
    try:
        with mo_web(link, timeout=120) as r, open(part, "wb") as f:   # mo_web: chỉ http(s), kể cả chuyển hướng
            while True:
                khuc = r.read(1 << 16)
                if not khuc:
                    break
                n += len(khuc)
                if n > TRAN_MP3:
                    raise ValueError(f"tệp > {TRAN_MP3 // (1024 * 1024)} MB — không phải mp3 một câu")
                f.write(khuc)
        part.replace(dich)
    finally:
        part.unlink(missing_ok=True)


def nhan_ket_qua(g, raw, f_kq, so_lo, cau_theo_id, cache):
    """--nhan: kết quả món giọng (ket_qua.tep[{cau, link}], cau = số thứ tự 1.. trong lô) → tải về raw/cau_NNN.mp3."""
    p = doc_json(g / "CAN_DOC.json")
    if not p:
        sys.exit("🔴 Không có 04_giong/CAN_DOC.json — không biết lô nào ứng với kết quả này.")
    try:
        kq = json.loads(Path(f_kq).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"🔴 Không thấy tệp kết quả {f_kq}")
    except (OSError, UnicodeDecodeError, ValueError) as e:
        sys.exit(f"🔴 {f_kq} không đọc được / không phải JSON: {str(e)[:120]}")
    kq = kq.get("ket_qua", kq) if isinstance(kq, dict) else kq
    tep = kq.get("tep") if isinstance(kq, dict) else kq
    if not tep:
        sys.exit(f"🔴 {f_kq} không có ket_qua.tep[{{cau, link}}]")
    los = p.get("lo", [])
    if so_lo is None:
        if len(los) != 1:
            sys.exit(f"🔴 Phiếu có {len(los)} lô — thêm --lo <số lô> (1..{len(los)}).")
        so_lo = 1
    if not 1 <= so_lo <= len(los):
        sys.exit(f"🔴 --lo {so_lo} không có (phiếu có {len(los)} lô).")
    ds = los[so_lo - 1]["cau"]
    if not isinstance(tep, list) or not all(isinstance(x, dict) for x in tep):
        sys.exit(f"🔴 {f_kq}: ket_qua.tep phải là danh sách [{{cau, link}}]")
    la = [str(x.get("link"))[:80] for x in tep if not la_link_web(x.get("link"))]
    if la:   # chặn cả lượt: link file://, đường dẫn máy, ftp… không phải kết quả món giọng
        sys.exit(f"🔴 {f_kq}: chỉ nhận link http/https, gặp {len(la)} link khác: {la[:3]} — không tải gì")
    ok, hong = 0, []
    for x in tep:
        try:
            k = int(x.get("cau"))
        except (TypeError, ValueError):
            hong.append(f"cau={x.get('cau')!r} không phải số"); continue
        if not 1 <= k <= len(ds):
            hong.append(f"cau={k} ngoài lô"); continue
        muc = ds[k - 1]
        dich = raw / f"cau_{muc['id']:03d}.mp3"
        tam = dich.with_suffix(".tai.mp3")
        try:
            tai_ve(x["link"], tam)
        except Exception as e:  # noqa
            tam.unlink(missing_ok=True)
            hong.append(f"câu {muc['id']}: tải hỏng {str(e)[:80]}"); continue
        if not la_mp3(tam):
            tam.unlink(missing_ok=True); hong.append(f"câu {muc['id']}: tệp tải về không phải mp3"); continue
        tam.replace(dich)
        c = cau_theo_id.get(muc["id"])
        if c and c.get("vi") == muc["vi"]:
            cache[tag(c)] = bam(muc["vi"])
        ok += 1
    log(f"nhận lô {so_lo}: {ok}/{len(ds)} câu" + (f" · hỏng {len(hong)}: {hong[:5]}" if hong else ""))
    return ok


def ra_trim(src, ra):
    """mp3 1,0× → wav 48 kHz mono, tăng tốc ×toc_do_giong, bỏ lặng đầu/cuối (CapCut hay đệm 0,1–0,3 s)."""
    sl = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05"
    chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", src, "-af",
          f"aresample=48000,atempo={CAU_HINH['toc_do_giong']:.4f},{sl},areverse,{sl},areverse", "-ac", "1", ra], im=True)
    return ffprobe_dur(ra)


def nen(src, ra, he_so):
    chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", src, "-af", f"atempo={he_so:.4f}", ra], im=True)
    return ffprobe_dur(ra)


def tron_cau(ds, tong, ra, tam_dir):
    """ds = [(tệp wav, mốc ms)] → một wav mono 48 kHz dài đúng `tong` giây. Trộn từng lô ≤ LO_TRON tệp (wav float tạm), rồi trộn các lô."""
    def mot_luot(vao, ra_, f32):
        ins, filt = [], []
        for j, (f, ms) in enumerate(vao):
            ins += ["-i", str(f)]
            filt.append(f"[{j}:a]adelay={ms}|{ms}[a{j}]" if ms else f"[{j}:a]anull[a{j}]")
        fc = ";".join(filt) + ";" + "".join(f"[a{j}]" for j in range(len(vao))) + \
            f"amix=inputs={len(vao)}:normalize=0:duration=longest,apad=whole_dur={tong:.2f},atrim=0:{tong:.2f}[v]"
        chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[v]", "-ar", "48000",
              "-ac", "1", "-c:a", "pcm_f32le" if f32 else "pcm_s16le", ra_])
    if len(ds) <= LO_TRON:
        return mot_luot(ds, ra, False)
    phan = []
    try:
        for k in range(0, len(ds), LO_TRON):
            f = tam_dir / f"_tron_{k // LO_TRON:03d}.wav"
            phan.append(f); mot_luot(ds[k:k + LO_TRON], f, True)
        log(f"trộn {len(ds)} câu qua {len(phan)} lô")
        mot_luot([(f, 0) for f in phan], ra, False)   # ≤ 100 lô = 10.000 câu — đủ cho mọi tập
    finally:
        for f in phan:
            f.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b4_giong", description="B4 — giọng Việt khớp khe")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--giong", default="nu-de-thuong", help="tên giọng của món «Đọc lời bằng giọng CapCut»")
    ap.add_argument("--nhan", help="tệp JSON kết quả món giọng (ket_qua.tep[{cau, link}]) — tải mp3 về rồi chạy tiếp")
    ap.add_argument("--lo", type=int, help="số lô trong CAN_DOC.json ứng với --nhan (bắt buộc khi phiếu có > 1 lô)")
    ap.add_argument("--doc-lai", action="store_true", help="bỏ bộ nhớ, đọc lại mọi câu")
    ap.add_argument("--khong-rut-gon", action="store_true", help="không xin rút gọn lời, câu dài thì nén tới trần cứng")
    a = ap.parse_args(argv)
    can("ffmpeg"); can("ffprobe")
    d = tap_dir(a.tap)
    t = doc_tap(a.tap)
    cau, doi = doc_cau(d)
    if not cau:
        sys.exit("🔴 Thiếu 03_dich/cau.json / cau.tsv — chạy B3 trước")
    if doi:
        log(f"đọc {doi} câu đã sửa lời trong cau.tsv")
    g = d / "04_giong"
    raw, fit = g / "raw", g / "fit"
    raw.mkdir(parents=True, exist_ok=True); fit.mkdir(exist_ok=True)
    cache = {} if a.doc_lai else (doc_json(g / "cache.json") or {})
    theo_id = {c["id"]: c for c in cau}
    t0 = time.time()
    tms = CAU_HINH["tu_moi_giay"]

    # 1. nhận tiếng: kết quả --nhan, hoặc mp3 trợ lý tự đặt vào raw/ theo phiếu cũ
    if a.nhan:
        nhan_ket_qua(g, raw, a.nhan, a.lo, theo_id, cache)
    elif not a.doc_lai:
        n = nhan_phieu_cu(g, raw, theo_id, cache)
        if n:
            log(f"nhận {n} mp3 mới theo phiếu CAN_DOC.json")
    ghi_json(g / "cache.json", cache)

    thieu = [(c["id"], c["vi"]) for c in cau if c.get("vi") and (cache.get(tag(c)) != bam(c["vi"]) or not (raw / f"{tag(c)}.mp3").exists())]
    if thieu:
        cu = doc_json(g / "CAN_DOC.json") or {}
        trong_phieu = {(x["id"], x["vi"]): l["lo"] for l in cu.get("lo", []) for x in l["cau"]}
        (g / "CAN_RUT_GON.json").unlink(missing_ok=True)   # vòng rút gọn đã xong (lời đổi ⇒ đọc lại) — chỉ còn phiếu đọc
        # phiếu cũ còn đúng (cùng giọng, đủ câu) ⇒ giữ nguyên số lô để trợ lý nhận tiếp các lô còn lại
        if cu.get("giong") == a.giong and all(k in trong_phieu for k in thieu):
            con = sorted({trong_phieu[k] for k in thieu})
            log(f"⏸ CHỜ TRỢ LÝ: còn {len(thieu)} câu chưa có mp3, ở lô {con} của phiếu {g / 'CAN_DOC.json'}")
            sys.exit(CHO_TRO_LY)
        lo = chia_lo(thieu)
        ghi_json(d / "03_dich/cau.json", cau)
        lenh = f"python -m ptm.b4_giong --tap {a.tap} --nhan <tệp kết quả lô k>" + (" --lo <k>" if len(lo) > 1 else "")
        cho_tro_ly(g / "CAN_DOC.json", f"Đọc {len(thieu)} câu bằng món «{CONG_CU_GIONG}»",
                   cong_cu=CONG_CU_GIONG, thu_muc_tap=str(d), ts=time.time(), giong=a.giong, toc_do=1.0, so_cau=len(thieu), so_lo=len(lo),
                   cach_lam=[f"Mỗi lô gọi món một lần: danh sách «vi» theo đúng thứ tự, giọng «{a.giong}», tốc độ 1,0 (máy tự tăng ×{CAU_HINH['toc_do_giong']}).",
                             "Kết quả trả mỗi câu một link mp3 (ket_qua.tep[{cau, link}], cau = số thứ tự trong lô, đếm từ 1).",
                             f"Cách 1: lưu JSON kết quả lô k ra tệp rồi chạy: {lenh}",
                             "Cách 2: tự tải từng link về đúng «tep» ghi ở mỗi câu, xong chạy lại: python -m ptm.b4_giong --tap " + a.tap],
                   lo=[{"lo": k, "so_ky_tu": sum(len(v) for _, v in ds),
                        "cau": [{"id": i, "vi": v, "tep": f"04_giong/raw/cau_{i:03d}.mp3", "md5_cu": md5_tep(raw / f"cau_{i:03d}.mp3")} for i, v in ds]}
                       for k, ds in enumerate(lo, 1)])
    (g / "CAN_DOC.json").unlink(missing_ok=True)

    # 2. khe thời gian + đo giọng đã tăng tốc. Khe không vượt quá đuôi phim (tron_cau cắt ở `tong`).
    tong = (t.get("video") or {}).get("dur") or ffprobe_dur(d / "01_raw/goc.mp4")
    for i, c in enumerate(cau):
        sau = cau[i + 1]["start"] if i + 1 < len(cau) else min(tong + 0.12, c["end"] + 5)   # câu cuối: được chạy sát đuôi phim
        # sàn 0,6 s: giữ đúng như dây chuyền gốc (đã chỉnh trên kênh) — cố ý không đổi
        khe = max(0.6, min(sau - 0.12, c["end"] + CAU_HINH["tran_giay"]) - c["start"])
        c["khe"] = round(max(0.05, min(khe, tong - c["start"])), 2)
        # trần nén cứng chốt theo khe GỐC (trước khi mượn khe): câu 2–4 chữ khe ngắn nén tới 1,30 vẫn nghe được
        c["_tran"] = 1.30 if c["khe"] < 1.2 else CAU_HINH["atempo_cung"]
    dai = []
    for c in cau:
        if not c.get("vi"):
            continue
        dur = ra_trim(raw / f"{tag(c)}.mp3", fit / f"{tag(c)}_trim.wav")
        c["_dur"] = math.ceil(dur * 100) / 100             # làm tròn LÊN 0,01 s; _ty tính từ CÙNG số này ⇒ _ty > trần thì bước 4 thiếu ≥ 0,01 s
        c["_ty"] = round(c["_dur"] / c["khe"], 3)
        if c["_ty"] > CAU_HINH["atempo_max"]:
            dai.append(c)

    # 3. câu quá dài: xin trợ lý rút gọn MỘT lần cho mỗi lời (đã hỏi lời này rồi mà vẫn giữ ⇒ coi như chấp nhận, đi tiếp)
    da_hoi = doc_json(g / "da_hoi_rut_gon.json") or {}
    hoi = [c for c in dai if not a.khong_rut_gon and da_hoi.get(str(c["id"])) != bam(c["vi"])]
    if hoi:
        for c in hoi:
            da_hoi[str(c["id"])] = bam(c["vi"])
        ghi_json(g / "da_hoi_rut_gon.json", da_hoi)
        ghi_json(d / "03_dich/cau.json", cau)
        cho_tro_ly(g / "CAN_RUT_GON.json", f"Viết lại {len(hoi)} câu ngắn hơn cho vừa khe thời gian", thu_muc_tap=str(d),
                   cach_lam=["Mỗi câu: viết lại NGẮN HƠN, không quá «so_tu_toi_da» từ, giữ ý chính, chủ ngữ, tên Hán-Việt và cách xưng hô của bộ; bỏ từ đệm.",
                             "Sửa thẳng cột vi (cột 4) của đúng dòng id trong 03_dich/cau.tsv, không đụng dòng khác.",
                             f"Xong chạy lại: python -m ptm.b4_giong --tap {a.tap} (máy sẽ xin đọc lại các câu đổi lời qua CAN_DOC.json).",
                             "Câu nào không rút được thì để nguyên — máy nén cứng tới trần, không hỏi lại."],
                   cau=[{"id": c["id"], "vi": c["vi"], "zh": c.get("zh", ""), "khe_giay": c["khe"], "giong_giay": c["_dur"],
                         "so_tu_hien_tai": len(c["vi"].split()), "so_tu_toi_da": max(2, int(c["khe"] * tms * 0.88))} for c in hoi])
    (g / "CAN_RUT_GON.json").unlink(missing_ok=True)

    # 4. MƯỢN KHE CÂU SAU: câu i vẫn dài sau khi nén tới trần thì lùi giọng câu i+1 vào phần lặng dư của nó (≤ 1,2 s, mỗi câu một lần)
    for c in cau:
        c["_start_giong"] = c["start"]
    for i, c in enumerate(cau[:-1]):
        if not c.get("vi") or "_ty" not in c:
            continue
        tran = c["_tran"]
        if c["_ty"] <= tran:
            continue
        thieu_giay = math.ceil((c["_dur"] / tran - c["khe"]) * 100) / 100   # làm tròn LÊN 0,01 s: khe tròn 2 số vẫn đủ cho trần
        s_ = cau[i + 1]
        # mượn phần DƯ trong khe câu sau (khe − giọng), không dùng khoảng lặng tự nhiên giữa câu — giữ đúng dây chuyền gốc, cố ý
        if s_.get("vi"):
            du = s_.get("khe", 0) - s_.get("_dur", 0)
        else:   # câu sau không lời ⇒ phần lặng dư kéo tới câu CÓ lời kế tiếp (hết phim thì +5 s)
            ke = next((x for x in cau[i + 2:] if x.get("vi")), None)
            du = (ke["_start_giong"] if ke else min(tong, c["end"] + 5.0)) - (c["start"] + c["khe"]) - 0.12
        if 0 < thieu_giay <= min(1.2, du - 0.05):
            c["khe"] = round(c["khe"] + thieu_giay, 2); s_["_start_giong"] = round(s_["_start_giong"] + thieu_giay, 2)
            s_["khe"] = round(s_["khe"] - thieu_giay, 2); c["_ty"] = round(c["_dur"] / c["khe"], 3); c["_muon"] = thieu_giay
            if s_.get("_dur") is not None:   # khe câu cho mượn co lại ⇒ tỉ lệ của nó cũng đổi
                s_["_ty"] = round(s_["_dur"] / max(0.05, s_["khe"]), 3)

    # 5. nén + đặt từng câu vào mốc
    khop, vao = [], []
    for c in cau:
        if not c.get("vi"):
            khop.append({"id": c["id"], "trang_thai": "KHONG_LOI"}); continue
        src = fit / f"{tag(c)}_trim.wav"
        ty, tt = c["_ty"], "OK"
        tran_cung = c["_tran"]   # cùng trần với bước 4 (chốt theo khe gốc)
        if ty > 1.0:
            he = min(ty, tran_cung)
            nen(src, fit / f"{tag(c)}.wav", he)
            src = fit / f"{tag(c)}.wav"
            tt = "NEN" if he <= CAU_HINH["atempo_max"] else "NEN_CUNG"
            if ty > tran_cung:
                tt = "VAN_DAI"
        khop.append({"id": c["id"], "khe": c["khe"], "dur": c["_dur"], "ty_le": ty, "trang_thai": tt, "vi": c["vi"],
                     **({"muon_khe_sau": round(c["_muon"], 2)} if c.get("_muon") else {}),
                     **({"lui": round(c["_start_giong"] - c["start"], 2)} if c["_start_giong"] != c["start"] else {})})
        vao.append((src, int(c["_start_giong"] * 1000)))
    if not vao:
        sys.exit("🔴 Không câu nào có lời Việt")
    tron_cau(vao, tong, g / "giong_viet.wav", fit)
    for c in cau:
        for k in ("_start_giong", "_muon", "_tran"):
            c.pop(k, None)
    ghi_json(g / "khop.json", khop)
    ghi_json(d / "03_dich/cau.json", cau)
    dem = {}
    for k in khop:
        dem[k["trang_thai"]] = dem.get(k["trang_thai"], 0) + 1
    log(f"xong giong_viet.wav · {dem} · {time.time() - t0:.0f}s")
    for k in [k for k in khop if k["trang_thai"] in ("NEN_CUNG", "VAN_DAI")][:10]:
        print(f"  ⚠️ câu {k['id']}: khe {k['khe']}s, giọng {k['dur']}s ({k['ty_le']}×) — {k['vi'][:60]}")
    xong_buoc(a.tap, "b4_giong", **dem, giong=a.giong, giay=round(time.time() - t0))


if __name__ == "__main__":
    main()
