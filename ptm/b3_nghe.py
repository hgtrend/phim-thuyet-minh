"""B3 — NGHE + ĐỌC CHỮ: ra bảng câu có mốc giây và ngân sách từ; phần DỊCH do trợ lý AI của người dùng làm.

1. Whisper (ptm.chung.nghe_chu) nghe `02_tieng/htdemucs/vocals.wav` tiếng Trung → mốc câu.
2. Chữ Hán in trên màn (1 hình/giây, ptm.ocr) bù những câu tai không nghe ra.
3. RapidOCR đọc dòng phụ đề in chết tại giữa mỗi câu (phụ đề in là NGUYÊN VĂN, Whisper chỉ là bản nghe).
4. Câu chưa có lời Việt ⇒ ghi phiếu `03_dich/CAN_DICH.json` rồi thoát mã 3. Trợ lý điền cột vi (cột 4) của `03_dich/cau.tsv`,
   chạy lại bước này: máy soát (không rỗng, không còn chữ Hán), chép lời vào cau.json, đánh dấu xong.

Ra: 03_dich/asr.json · ocr_sub.json · cau.json · cau.tsv.

    python -m ptm.b3_nghe --tap <slug> [--khong-ocr] [--dich-lai] [--bo <bảng tên của bộ .md>]

--bo: bảng TÊN + XƯNG HÔ của bộ phim để dịch nhất quán. Không ghi thì máy tự tìm <tập>/bo.md, rồi <thư mục gốc>/bo/<tên bộ>.md
      (tên bộ = tên tập bỏ tiền tố T<số>_, vd T01_ten_bo → bo/ten_bo.md).
"""
import argparse, re, sys, time
from pathlib import Path

from .chung import CAU_HINH, CJK, cho_tro_ly, doc_json, doc_tap, doc_tsv, ffprobe_video, ghi_json, ghi_tsv, goc_du_an, log, nghe_chu, \
    tap_dir, xong_buoc
from .ocr import ocr_giua_cau, ocr_khung

LOI_NHAC = "以下是普通话的对白字幕。"


def nghe(vocals):
    ra, truoc = [], None
    for s in nghe_chu(vocals, "zh", LOI_NHAC):
        t = s["text"].strip()
        dur = s["end"] - s["start"]
        if not CJK.search(t) or dur < 0.25:
            continue
        if truoc and t == truoc["zh"] and s["start"] - truoc["end"] < 0.3:   # Whisper lặp câu = ảo giác
            continue
        truoc = {"start": round(s["start"], 2), "end": round(s["end"], 2), "zh": t}
        ra.append(truoc)
    return ra


def cau_tu_chu(goc, asr, W, H, d):
    """Whisper là tai DUY NHẤT ⇒ câu nào nó không nghe ra là MẤT HẲN. Nên quét chữ Hán in trên màn 1 hình/giây; khoảng chữ nào không trùng
    câu Whisper nào thì thành câu mới, kèm ô toạ độ để B5 vẽ chữ Việt đè đúng chỗ."""
    h = d / "05_hinh"; h.mkdir(exist_ok=True)
    _, ocr = ocr_khung(goc, h, W, H)
    # ô phụ đề: nửa dưới khung, cao vừa cỡ chữ, đủ rộng — bỏ ô TĨNH (xuất hiện ≥ 40% số khung = logo/watermark)
    dem = {}
    for k in ocr:
        for o in k["o"]:
            dem[(round(o["x1"] / W * 40), round(o["y1"] / H * 40))] = dem.get((round(o["x1"] / W * 40), round(o["y1"] / H * 40)), 0) + 1
    n = max(1, len(ocr))
    o_sub = []
    for k in ocr:
        for o in k["o"]:
            cao_ok = 0.02 * H <= o["y2"] - o["y1"] <= 0.13 * H
            if (o["y1"] + o["y2"]) / 2 / H > 0.60 and cao_ok and (o["x2"] - o["x1"]) >= 0.06 * W \
               and CJK.search(o["chu"] or "") and dem[(round(o["x1"] / W * 40), round(o["y1"] / H * 40))] < 0.4 * n:
                o_sub.append((k["t"], o))

    # gom thành khoảng chữ: giây liền nhau (≤ 2 s) VÀ CÙNG MỘT CÂU — gom theo thời gian không thôi thì nhiều câu dính thành một cụm 30 s.
    def giong(a, b):
        a, b = (a or "").strip(), (b or "").strip()
        if not a or not b:
            return False
        if a in b or b in a:
            return True
        chung = len(set(a) & set(b))
        return chung >= 0.6 * min(len(set(a)), len(set(b)))

    cum, cur = [], None
    for t, o in sorted(o_sub, key=lambda x: x[0]):
        chu = o["chu"] or ""
        if cur and t - cur["t2"] <= 2 and giong(chu, cur["chu_cuoi"]) and t - cur["t1"] <= 8:
            cur["t2"] = t; cur["o"].append(o); cur["chu_cuoi"] = chu
        else:
            cur = {"t1": t, "t2": t, "o": [o], "chu_cuoi": chu}; cum.append(cur)
    co = [(c["start"], c["end"]) for c in asr]
    them = []
    for c in cum:
        a, b = c["t1"] - 0.4, c["t2"] + 1.0
        chu0 = re.sub(r"[^一-鿿]", "", max((o["chu"] or "" for o in c["o"]), key=len))
        gan = [x for x in asr if x["start"] < b + 1.5 and x["end"] > a - 1.5]
        van = re.sub(r"[^一-鿿]", "", "".join(x["zh"] for x in gan))
        if chu0 and len(chu0) >= 2 and (chu0 in van or sum(1 for ch in set(chu0) if ch in van) >= 0.7 * len(set(chu0))):
            continue                                   # tai đã nghe ra đúng câu này rồi (so theo CHỮ, không chỉ theo giờ)
        if any(min(b, y2) - max(a, y1) > 0.3 * (b - a) for y1, y2 in co):
            continue                                   # đã có câu phủ khoảng này
        chu = max((o["chu"] or "" for o in c["o"]), key=len)
        b = min(b, a + 9.0)                            # câu thoại không dài quá ~9 s
        if len(chu) < 2:
            continue
        box = {"x1": min(o["x1"] for o in c["o"]), "y1": min(o["y1"] for o in c["o"]),
               "x2": max(o["x2"] for o in c["o"]), "y2": max(o["y2"] for o in c["o"])}
        them.append({"start": round(max(0, a), 2), "end": round(b, 2), "zh": chu, "tu_chu": True, "o_chu": box})
    return them


def ngan_sach(c):
    return max(2, int((c["end"] - c["start"]) * CAU_HINH["tu_moi_giay"]))


def tim_bo(slug, d, chi_dinh):
    if chi_dinh:
        p = Path(chi_dinh).expanduser().resolve()
        if not p.exists():
            sys.exit(f"🔴 --bo: không thấy {p}")
        return p
    for p in (d / "bo.md", goc_du_an() / "bo" / (re.sub(r"^T\d+_", "", slug) + ".md")):
        if p.exists():
            return p
    return None


def tua_goc(d, t):
    """Tựa video gốc: B1 ghi nguon.tieu_de (bản cũ ghi «tua»); không có thì lấy «tua» của B0 (00_do_trung/do_trung.json)."""
    ng = t.get("nguon") or {}
    return ng.get("tieu_de") or ng.get("tua") or (doc_json(d / "00_do_trung/do_trung.json") or {}).get("tua") or ""


def luat_dich(tms):
    """Luật dịch — giữ nguyên tinh thần lời dặn model dịch của dây chuyền gốc."""
    return [
        "Dịch lời thoại hoạt hình Trung Quốc sang TIẾNG VIỆT NÓI để thuyết minh: tự nhiên như người Việt nói, ngắn gọn, giữ đúng ý và cảm xúc.",
        f"Số từ mỗi câu KHÔNG vượt `toi_da_tu` (= số giây × {tms} từ/giây, tối thiểu 2) — câu dài thì cắt ý phụ.",
        "Tên người / địa danh / chiêu thức phiên âm HÁN-VIỆT (vd 叶凡 → Diệp Phàm). KHÔNG để chữ Hán, KHÔNG phiên âm pinyin.",
        "Tên riêng và xưng hô NHẤT QUÁN trong cả tập (và cả bộ nếu có bảng tên `bo`) — bảng tên của bộ bắt buộc theo, ưu tiên hơn thói quen dịch.",
        "Không thêm câu dắt, không giải thích, không ghi chú trong lời.",
        "Mỗi câu có `nghe` (Whisper nghe, có thể sai chữ) và `chu_in` (phụ đề in trên hình). Khi `chu_in` có chữ, không rác và khác `nghe` thì DỊCH THEO `chu_in`.",
        "Giữ TỪ NHẤN của câu gốc (精准 = chính xác, 居然 = lại còn, 好玩的 = thứ hay ho…).",
        "小哥哥 / 小姐姐 = anh chàng / cô nàng (không phải anh trai / chị gái ruột).",
        "Câu phải trọn nghĩa, có tân ngữ, đừng cụt.",
        "Mọi câu đều phải có lời Việt; câu chỉ là tiếng kêu / thở thì dịch thành thán từ ngắn (vd «Hả?», «Ừ.»).",
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b3_nghe", description="B3 — nghe chữ Trung + đọc chữ trên hình; dịch do trợ lý làm qua phiếu")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--khong-ocr", action="store_true", help="không đọc chữ trên hình (chỉ Whisper)")
    ap.add_argument("--dich-lai", action="store_true", help="xoá lời Việt cũ, ra phiếu dịch lại")
    ap.add_argument("--bo", default=None, help="bảng TÊN + XƯNG HÔ của bộ (.md) để dịch nhất quán")
    a = ap.parse_args(argv)
    d = tap_dir(a.tap)
    t = doc_tap(a.tap)
    goc, vocals = d / "01_raw/goc.mp4", d / "02_tieng/htdemucs/vocals.wav"
    if not goc.exists():
        sys.exit(f"🔴 thiếu 01_raw/goc.mp4 — chạy B1 trước: python -m ptm nhan --tap {a.tap} …")
    if not vocals.exists():
        sys.exit(f"🔴 thiếu 02_tieng/htdemucs/vocals.wav — chạy B2 trước: python -m ptm tach-tieng --tap {a.tap}")
    ra = d / "03_dich"
    ra.mkdir(exist_ok=True)
    t0 = time.time()
    asr = doc_json(ra / "asr.json")
    if not asr:
        asr = nghe(vocals)
        ghi_json(ra / "asr.json", asr)
        log(f"Whisper: {len(asr)} câu")
    else:
        log(f"đã có asr.json: {len(asr)} câu")
    vi = t.get("video") or ffprobe_video(goc)
    if not a.khong_ocr:
        bu = cau_tu_chu(goc, asr, vi["w"], vi["h"], d)
        if bu:
            log(f"chữ trên màn bù thêm {len(bu)} câu Whisper không nghe ra: " + ", ".join(f"{x['start']:.0f}s «{x['zh'][:12]}»" for x in bu[:6]))
            asr = sorted(asr + bu, key=lambda x: x["start"])
            ghi_json(ra / "asr.json", asr)
    cau = [{"id": i + 1, **s} for i, s in enumerate(asr)]
    if not a.khong_ocr:
        ocr = doc_json(ra / "ocr_sub.json")
        if not ocr or len(ocr) != len(cau):
            ocr = ocr_giua_cau(goc, cau, vi["w"], vi["h"], ra / "_khung_ocr")
            ghi_json(ra / "ocr_sub.json", ocr)
        for c, o in zip(cau, ocr):
            c["ocr"] = o
        log(f"OCR có chữ ở {sum(1 for o in ocr if o)}/{len(ocr)} câu")

    # khung câu: cau.json cũ cùng số câu ⇒ chép LỜI VIỆT cũ sang bảng mới (giữ OCR vừa đọc — lượt trước có thể chạy --khong-ocr);
    # khác số câu thì làm mới với vi rỗng
    cu = doc_json(ra / "cau.json")
    if cu and len(cu) == len(cau) and not a.dich_lai:
        for c, c_cu in zip(cau, cu):
            c["vi"] = c_cu.get("vi") or ""
            if "ocr" not in c and c_cu.get("ocr"):   # lượt này --khong-ocr ⇒ giữ chữ in đã đọc lượt trước
                c["ocr"] = c_cu["ocr"]
    else:
        if cu and not a.dich_lai:
            log(f"⚠️ cau.json cũ có {len(cu)} câu ≠ {len(cau)} câu mới ⇒ làm lại bảng câu, lời Việt cũ bỏ")
        for c in cau:
            c["vi"] = ""
    for c in cau:
        c["ngan_sach"] = ngan_sach(c)
    tsv = ra / "cau.tsv"
    if a.dich_lai or not tsv.exists() or [h["id"] for h in doc_tsv(tsv)] != [c["id"] for c in cau]:
        if tsv.exists() and not a.dich_lai and any(h["vi"] for h in doc_tsv(tsv)):
            log("⚠️ cau.tsv cũ không khớp id với bảng câu mới ⇒ ghi lại (lời cũ trong tsv bỏ)")
        ghi_tsv(tsv, cau)
    # lời Việt lấy từ cột vi của cau.tsv (trợ lý / người dùng sửa ở đó)
    vi_tsv = {h["id"]: re.sub(r"\s+", " ", h["vi"]).strip() for h in doc_tsv(tsv)}
    for c in cau:
        c["vi"] = vi_tsv.get(c["id"], "")
        c["so_tu"] = len(c["vi"].split())
    ghi_json(ra / "cau.json", cau)

    rong = [c["id"] for c in cau if not c["vi"]]
    con_han = [c["id"] for c in cau if CJK.search(c["vi"])]
    if rong or con_han:
        bo = tim_bo(a.tap, d, a.bo)
        can_dich = [c for c in cau if c["id"] in set(rong) | set(con_han)]
        log(f"{len(rong)} câu chưa có lời Việt · {len(con_han)} câu còn chữ Hán ⇒ ra phiếu dịch")
        cho_tro_ly(ra / "CAN_DICH.json", "dịch lời thoại sang tiếng Việt thuyết minh",
                   tap=a.tap, ten_bo=t.get("cot_loi") or a.tap, boi_canh=tua_goc(d, t)[:300],
                   tep_dien=str(tsv), cot_dien="cột 4 «vi» (cột tách bằng TAB: id, start, end, vi, zh) — giữ nguyên id/start/end/zh, một câu một dòng, không xuống dòng trong lời",
                   bo=str(bo) if bo else None, tu_moi_giay=CAU_HINH["tu_moi_giay"], luat=luat_dich(CAU_HINH["tu_moi_giay"]),
                   cau_chua_dich=rong, cau_con_chu_han=con_han,
                   cau=[{"id": c["id"], "giay": round(c["end"] - c["start"], 1), "toi_da_tu": c["ngan_sach"],
                         "nghe": c["zh"], "chu_in": c.get("ocr") or ""} for c in can_dich],
                   xong_thi_chay=f"python -m ptm.b3_nghe --tap {a.tap}")
    phieu = ra / "CAN_DICH.json"
    if phieu.exists():
        phieu.unlink()                                  # đã dịch đủ ⇒ phiếu cũ hết hiệu lực
    qua = [c["id"] for c in cau if c["so_tu"] > c["ngan_sach"] + 2]
    log(f"xong {len(cau)} câu · vượt ngân sách từ: {len(qua)} {qua[:10]} · {time.time() - t0:.0f}s")
    for c in cau[:6]:
        print(f"  {c['id']:3} {c['start']:7.2f}–{c['end']:7.2f} [{c['so_tu']}/{c['ngan_sach']}] {c['vi']}   ⟵ {c['zh']}")
    xong_buoc(a.tap, "b3_nghe", so_cau=len(cau), vuot_ngan_sach=len(qua), giay=round(time.time() - t0))


if __name__ == "__main__":
    main()
