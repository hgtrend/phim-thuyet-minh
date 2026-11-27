"""B0 — DÒ TRÙNG: bộ phim này đã có kênh Việt nào làm trên YouTube chưa? Chạy TRƯỚC khi nhận video (B1 chặn nếu chưa dò hoặc ĐỎ).

    python -m ptm.b0_do_trung --tap T01 --ket-qua lay_link.json --bien-the "<tên Hán-Việt>|<tên dịch nghĩa>"   # tựa + link lấy từ kết quả món HG Trend
    python -m ptm.b0_do_trung --tap T01 --tua "《<tên bộ>》第1集" --bien-the "<tên Hán-Việt>|<tên dịch nghĩa>" [--bia anh_bia.jpg]

Dò bằng: (1) TÊN — tựa gốc, tên bộ rút từ tựa, các biến thể tên tiếng Việt TRỢ LÝ của bạn đưa (tên Hán-Việt, tên dịch nghĩa), kèm đuôi
«vietsub / thuyết minh»; (2) BÌA — có ảnh bìa nguồn (--bia) thì so vân tay ảnh với bìa từng video YouTube tìm được.
Cần yt-dlp (tìm trên YouTube, không tải video). Mã thoát: 0 🟢 XANH · 1 🟡 VÀNG (cần mắt xem) · 2 🔴 ĐỎ (đã có bản Việt / bìa trùng).
Kênh của chính bạn: --kenh-minh "Tên kênh" (video của kênh mình không tính là trùng).
"""
import argparse, json, re, shutil, subprocess, sys, time
from difflib import SequenceMatcher
from pathlib import Path

from .chung import CJK, doc_tap, ghi_json, ghi_tap, la_link_web, log, mo_web, tap_dir, xong_buoc

TU_KHOA_VIET = ["vietsub", "thuyết minh", "lồng tiếng", "tập ", "full", "review", "mạn kịch", "truyện", "hoạt hình", "trọn bộ", "phần "]


def lam_sach_tua(t):
    t = re.sub(r"#\S+", " ", t or "")
    t = re.sub(r"[【】《》\[\]\(\)（）|｜\-_\*~!！?？:：,，。.、·🔥✨💥👉⚡️]", " ", t)
    return " ".join(t.split())


def ten_cot_loi(tua):
    """Tên bộ truyện từ tựa Bilibili / Douyin: ưu tiên 《…》, rồi 【…】, rồi đoạn dài nhất trước dấu ngăn."""
    t = tua or ""
    m = re.search(r"《([^》]{2,40})》", t)
    if m:
        return m.group(1).strip()
    m = re.search(r"【([^】]{2,40})】", t)
    if m and not re.search(r"新番|全集|动漫|动态漫|合集|完结|最新", m.group(1)):
        return m.group(1).strip()
    t = re.sub(r"【[^】]*】|#\S+|第\s*\d+\s*[集话話]|EP-?\d+|\d+-\d+集?|4K|高清|一口气看完|无拼接|全集", " ", t)
    parts = [p.strip() for p in re.split(r"[|｜/／—\-:：!！?？,，。、]", t) if len(p.strip()) >= 4]
    return (parts[0] if parts else lam_sach_tua(tua))[:40]


def co_dau_viet(s):
    return bool(re.search(r"[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", s or ""))


def tim_youtube(yt, q, n=8):
    cmd = [yt, "--socket-timeout", "20", "--flat-playlist", "--print",
           "%(id)s\t%(channel,uploader)s\t%(title)s\t%(view_count)s\t%(duration)s\t%(upload_date)s", f"ytsearch{n}:{q}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        log(f"⚠️ tìm YouTube quá giờ: {q}")
        return None
    if r.returncode != 0:                                   # mất mạng / YouTube chặn / yt-dlp cũ ⇒ KHÔNG được coi là «không thấy»
        log(f"⚠️ yt-dlp lỗi ({r.returncode}) với «{q}»: {(r.stderr or '').strip()[-200:]}")
        return None
    ra = []
    for ln in r.stdout.splitlines():
        p = ln.split("\t")
        if len(p) < 6 or not re.fullmatch(r"[0-9A-Za-z_\-]{6,20}", p[0]):   # mã video lạ thì bỏ (mã còn dùng làm tên tệp ảnh)
            continue
        ra.append({"id": p[0], "kenh": p[1], "tua": p[2], "xem": int(p[3]) if p[3].isdigit() else 0,
                   "giay": float(p[4]) if p[4].replace(".", "", 1).isdigit() else 0, "ngay": p[5],
                   "url": f"https://www.youtube.com/watch?v={p[0]}", "truy_van": q})
    return ra


def tai_anh(url, ra):
    if not la_link_web(url):
        return False
    try:
        with mo_web(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}, 30) as r:
            b = r.read(10 * 1024 * 1024)
        if len(b) > 1000:
            Path(ra).write_bytes(b)
            return True
    except Exception:
        pass
    return False


def van_tay(p):
    """pHash + dHash của ảnh và bản cắt viền 8% / 15% (bìa đăng lại hay thêm chữ, cắt mép)."""
    from PIL import Image
    import imagehash
    im = Image.open(p).convert("RGB")
    w, h = im.size
    ra = []
    for c in (0.0, 0.08, 0.15):
        cr = im.crop((int(w * c), int(h * c), int(w * (1 - c)), int(h * (1 - c)))).resize((320, 180))
        ra.append((imagehash.phash(cr), imagehash.dhash(cr)))
    return ra


def khoang_cach_bia(vt_nguon, vt_ung):
    return min(((p1 - p2) + (d1 - d2)) / 2 for p1, d1 in vt_nguon for p2, d2 in vt_ung)


def gian_the(s):
    try:
        from zhconv import convert                      # phồn → giản (kênh Đài / Hồng Kông viết 藥香奪嫡, nguồn viết 药香夺嫡); không có thì bỏ qua
        return convert(s, "zh-cn")
    except Exception:
        return s


def chuoi_giong(a, b):
    a, b = gian_the(lam_sach_tua(a).lower()), gian_the(lam_sach_tua(b).lower())
    sm = SequenceMatcher(None, a, b).ratio()
    ca, cb = CJK.findall(a), CJK.findall(b)
    ba, bb = {x + y for x, y in zip(ca, ca[1:])}, {x + y for x, y in zip(cb, cb[1:])}   # so cặp chữ Hán liền nhau, không so chữ rời
    han = len(ba & bb) / len(ba) if len(ba) >= 2 else 0
    return max(sm, han)


def cham(tua, cot_loi, bien_the, ung, bia_kc):
    tua_u = ung["tua"]
    d_goc, d_full = chuoi_giong(cot_loi, tua_u), chuoi_giong(tua, tua_u)
    d_viet = max([chuoi_giong(b, tua_u) for b in bien_the] + [0])
    tu_l = (tua_u + " " + (ung["kenh"] or "")).lower()
    viet = co_dau_viet(tua_u) or co_dau_viet(ung["kenh"] or "") or any(k in tu_l for k in TU_KHOA_VIET)
    ly_do, muc = [], "xanh"
    if bia_kc <= 8:
        muc = "do"; ly_do.append(f"bìa trùng (khoảng cách {bia_kc:.0f})")
    if d_viet >= 0.70 and viet:
        muc = "do"; ly_do.append(f"tên tiếng Việt trùng {d_viet:.2f}")
    if (d_goc >= 0.6 or d_full >= 0.55) and viet:
        muc = "do"; ly_do.append("tên bộ trùng + kênh / tựa tiếng Việt")
    if muc != "do":
        if d_goc >= 0.6 or d_full >= 0.55:
            muc = "vang"; ly_do.append(f"tên trùng bản Trung đăng lại ({max(d_goc, d_full):.2f})")
        if 8 < bia_kc <= 13:
            muc = "vang"; ly_do.append(f"bìa gần giống ({bia_kc:.0f})")
        if d_viet >= 0.58:
            muc = "vang"; ly_do.append(f"tên Việt gần giống {d_viet:.2f}")
    return muc, ly_do, {"d_goc": round(d_goc, 2), "d_full": round(d_full, 2), "d_viet": round(d_viet, 2), "viet": viet, "bia": bia_kc}


def main(argv=None):
    ap = argparse.ArgumentParser(description="B0 — dò trùng trên YouTube")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--ket-qua", help="tệp JSON kết quả món HG Trend «Lấy link tải video» (lấy tựa + link)")
    ap.add_argument("--tua", help="tựa gốc của video (khi không có --ket-qua)")
    ap.add_argument("--ten-bo", help="tên bộ phim tiếng Trung (bỏ trống: máy rút từ tựa)")
    ap.add_argument("--bien-the", default="", help="tên tiếng Việt có thể có, ngăn bằng | (Hán-Việt, dịch nghĩa) — trợ lý đưa")
    ap.add_argument("--bia", help="ảnh bìa nguồn (tệp hoặc link) để so vân tay")
    ap.add_argument("--kenh-minh", default="", help="tên kênh của bạn (không tính là trùng), ngăn bằng |")
    ap.add_argument("--so-ket-qua", type=int, default=8)
    a = ap.parse_args(argv)
    yt = shutil.which("yt-dlp")
    if not yt:
        sys.exit("🔴 Cần yt-dlp để tìm trên YouTube: «pip install yt-dlp»")
    link = None
    tua = a.tua
    if a.ket_qua:
        try:
            d = json.loads(Path(a.ket_qua).read_text(encoding="utf-8"))
            d = (d.get("ket_qua") or d) if isinstance(d, dict) else {}
            v = d.get("video") if isinstance(d, dict) and isinstance(d.get("video"), dict) else {}
        except (OSError, ValueError):
            sys.exit(f"🔴 Không đọc được tệp kết quả {a.ket_qua}")
        tua, link = tua or v.get("tieu_de"), v.get("link")
    if not tua:
        sys.exit("🔴 Cần --tua hoặc --ket-qua")
    d = tap_dir(a.tap) / "00_do_trung"
    (d / "ung_vien").mkdir(parents=True, exist_ok=True)
    cot_loi = a.ten_bo or ten_cot_loi(tua)
    bien_the = [b.strip() for b in a.bien_the.split("|") if b.strip()]
    if not bien_the:
        log("🟡 Chưa có biến thể tên tiếng Việt (--bien-the) — dò bằng tên Việt sẽ hụt. Nhờ trợ lý dịch tên bộ (Hán-Việt + nghĩa).")
    vt_nguon = None
    if a.bia:
        f = d / "bia_nguon.jpg"
        if Path(a.bia).is_file():
            if Path(a.bia).resolve() != f.resolve():
                shutil.copy2(a.bia, f)
        elif not la_link_web(a.bia):
            sys.exit(f"🔴 --bia: không thấy tệp {a.bia} (hoặc đưa link http/https)")
        elif not tai_anh(a.bia, f):
            log("⚠️ không tải được ảnh bìa — chỉ dò bằng tên"); f = None
        if f:
            try:
                vt_nguon = van_tay(f)
            except Exception as e:
                log(f"⚠️ ảnh bìa hỏng ({e}) — chỉ dò bằng tên")
    log(f"tựa: {tua[:80]} · tên bộ: {cot_loi} · biến thể: {bien_the} · bìa: {'có' if vt_nguon else 'không'}")
    truy_van = [cot_loi, lam_sach_tua(tua)[:60], f"{cot_loi} vietsub", f"{cot_loi} thuyết minh"] + bien_the[:3] + [f"{b} tập 1" for b in bien_the[:1]]
    truy_van = list(dict.fromkeys(q for q in truy_van if q and len(q.strip()) > 1))
    ung, seen, hong = [], set(), 0
    for q in truy_van:
        r = tim_youtube(yt, q, a.so_ket_qua)
        if r is None:
            hong += 1
            continue
        for u in r:
            if u["id"] not in seen:
                seen.add(u["id"]); ung.append(u)
    if hong == len(truy_van):
        sys.exit("🔴 Mọi lượt tìm YouTube đều lỗi — chưa dò được (KHÔNG phải «chưa ai làm»). Kiểm tra mạng / cập nhật yt-dlp («pip install -U yt-dlp») rồi chạy lại.")
    if hong:
        log(f"🟡 {hong}/{len(truy_van)} lượt tìm lỗi — kết quả có thể thiếu")
    log(f"YouTube trả {len(ung)} ứng viên từ {len(truy_van)} truy vấn")
    kenh_minh = {k.strip().lower() for k in a.kenh_minh.split("|") if k.strip()}
    ket = []
    for u in ung:
        kc = 99
        if vt_nguon is not None:
            f = d / "ung_vien" / f"{u['id']}.jpg"
            if f.exists() or tai_anh(f"https://i.ytimg.com/vi/{u['id']}/hqdefault.jpg", f):
                try:
                    kc = khoang_cach_bia(vt_nguon, van_tay(f))
                except Exception as e:
                    log(f"⚠️ vân tay bìa {u['id']}: {e}")
        muc, ly_do, so = cham(tua, cot_loi, bien_the, u, kc)
        if (u.get("kenh") or "").strip().lower() in kenh_minh:
            muc, ly_do = "xanh", ["video của kênh mình"]
        ket.append({**u, "muc": muc, "ly_do": ly_do, **so})
    thu_tu = {"do": 0, "vang": 1, "xanh": 2}
    ket.sort(key=lambda x: (thu_tu[x["muc"]], -x["d_goc"], x["bia"]))
    muc_chung = "do" if any(k["muc"] == "do" for k in ket) else "vang" if any(k["muc"] == "vang" for k in ket) else "xanh"
    nhan = {"do": "🔴 ĐỎ — ĐÃ CÓ kênh Việt làm bộ này (hoặc bìa trùng). Không nên làm.",
            "vang": "🟡 VÀNG — có bản đăng lại / tên gần giống. Mở các link dưới xem tận mắt trước khi làm.",
            "xanh": "🟢 XANH — chưa thấy bản nào trùng."}[muc_chung]
    dong = ["# PHIẾU DÒ TRÙNG YOUTUBE", "", f"- Lúc: {time.strftime('%Y-%m-%d %H:%M')}", f"- Nguồn: {link or '(không có link)'}" + (f" · {hong}/{len(truy_van)} lượt tìm lỗi" if hong else ""),
            f"- Tựa gốc: {tua}", f"- Tên bộ: **{cot_loi}** · biến thể Việt: {', '.join(bien_the) or '(chưa có)'}",
            f"- Bìa nguồn: {'có, đã so' if vt_nguon else 'không có — chưa so bìa'}",
            f"- Truy vấn ({len(truy_van)}): " + " · ".join(f"`{q}`" for q in truy_van), "", f"## KẾT LUẬN MÁY: {nhan}", "",
            "| Mức | Kênh | Tựa | Lượt xem | Ngày | Dài | Tên bộ | Tên Việt | Bìa | Lý do | Link |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in ket[:25]:
        ic = {"do": "🔴", "vang": "🟡", "xanh": "⚪"}[k["muc"]]
        bia = "—" if k["bia"] >= 99 else f"{k['bia']:.0f}"
        dong.append(f"| {ic} | {k['kenh']} | {k['tua'][:60]} | {k['xem']:,} | {k['ngay']} | {int(k['giay'] // 60)}′ | {k['d_goc']} | {k['d_viet']} | {bia} | "
                    f"{'; '.join(k['ly_do'])} | {k['url']} |")
    dong += ["", "Bìa: khoảng cách vân tay 0–8 = trùng · 9–13 = gần giống · lớn hơn = khác. Tên: 0–1, ≥ 0,6 là trùng.", ""]
    if muc_chung == "vang":
        dong += ["## Việc cho bạn / trợ lý", "Mở từng link VÀNG, xem bìa và 15 giây đầu: cùng bộ phim không, có tiếng / phụ đề Việt không, kênh đó đã đăng bao "
                 "nhiêu tập. Cùng bộ + có tiếng Việt ⇒ coi như ĐỎ.", ""]
    (d / "PHIEU_DO_TRUNG.md").write_text("\n".join(dong), encoding="utf-8")
    ghi_json(d / "do_trung.json", {"tua": tua, "link": link, "cot_loi": cot_loi, "bien_the": bien_the, "truy_van": truy_van, "muc": muc_chung, "ung_vien": ket})
    ghi_tap(a.tap, cot_loi=cot_loi, do_trung=muc_chung)
    xong_buoc(a.tap, "b0_do_trung", muc=muc_chung, so_ung_vien=len(ket))
    print("\n" + nhan + f"\nPhiếu: {d / 'PHIEU_DO_TRUNG.md'}")
    for k in ket[:5]:
        print(f"  {k['muc']:5} {k['kenh'][:22]:22} {k['tua'][:55]:55} bộ={k['d_goc']} việt={k['d_viet']} bìa={k['bia'] if k['bia'] < 99 else '—'}")
    sys.exit({"xanh": 0, "vang": 1, "do": 2}[muc_chung])


if __name__ == "__main__":
    main()
