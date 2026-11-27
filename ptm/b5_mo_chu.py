"""B5 — TÌM CHỮ TRUNG trên hình để làm mờ + VẼ PHỤ ĐỀ VIỆT (PNG).

1. Rút khung 1 hình/giây (rộng 960) → RapidOCR (ptm.ocr). Ô chữ Hán ở đáy khung (y > 72%) = phụ đề in chết;
   ô lặp cùng chỗ ở ≥ 50% khung = logo/watermark tĩnh.
2. Ra `05_hinh/vung_mo.json`: dải phụ đề (x1,y1,x2,y2 theo khung gốc) + các khoảng giây có chữ; ô tĩnh (mờ suốt phim);
   ô «thêm» (chữ ngoài dải, có khoảng giây riêng); vị trí chữ Việt cho câu có chữ Trung dời chỗ. B7 làm mờ theo tệp này.
3. Vẽ phụ đề Việt từng câu bằng Pillow: vàng, viền đen, tối đa 2 dòng, phông Baloo 2 ExtraBold
   → `05_hinh/sub_png/cau_NNN.png` (ảnh trong suốt cả khung). Đi đường PNG để không phụ thuộc ffmpeg có libass/drawtext.

Lời Việt: cột vi của `03_dich/cau.tsv` (người dùng sửa ở đây), không có tsv thì `03_dich/cau.json`.
Vùng mờ thêm bằng tay (chữ dọc, chữ lạ OCR không đọc): `05_hinh/them_tay.json` = [{"x1","y1","x2","y2","chu","khoang":[[a,b],…]}].

    python -m ptm.b5_mo_chu --tap <slug> [--chi-sub]   (--chi-sub: chỉ vẽ lại phụ đề, không OCR lại)
"""
import argparse, json, math, sys, time

from .chung import CAU_HINH, FONT_SUB, doc_cau, doc_json, doc_tap, ffprobe_video, ghi_json, log, tap_dir, xong_buoc
from .ocr import ocr_khung


def gop_khoang(kh):
    """gộp các khoảng chồng/kề nhau (cách ≤0,3 s)"""
    kh = sorted([list(k) for k in kh]); ra = []
    for a, b in kh:
        if ra and a <= ra[-1][1] + 0.3:
            ra[-1][1] = max(ra[-1][1], b)
        else:
            ra.append([a, b])
    return ra


def phan_tich(ocr, W, H, cau=None):
    import numpy as np
    sub, tinh = [], {}
    for k in ocr:
        for o in k["o"]:
            hh = o["y2"] - o["y1"]
            yc = (o["y1"] + o["y2"]) / 2 / H
            if yc > 0.72 and 0.02 * H <= hh <= 0.13 * H and (o["x2"] - o["x1"]) >= 0.06 * W:
                sub.append((k["t"], o))
            key = (round(o["x1"] / W * 50), round(o["y1"] / H * 50), round((o["x2"] - o["x1"]) / W * 25))
            tinh.setdefault(key, []).append((k["t"], o))
    n = max(1, len(ocr))
    o_tinh = []
    for key, ds in tinh.items():
        if len(ds) >= 0.5 * n and len(ds) >= 5:
            xs1 = [o["x1"] for _, o in ds]; ys1 = [o["y1"] for _, o in ds]
            xs2 = [o["x2"] for _, o in ds]; ys2 = [o["y2"] for _, o in ds]
            o_tinh.append({"x1": max(0, min(xs1) - 8), "y1": max(0, min(ys1) - 8), "x2": min(W, max(xs2) + 8), "y2": min(H, max(ys2) + 8),
                           "chu": ds[0][1]["chu"], "ti_le_khung": round(len(ds) / n, 2)})

    # loại ô sub trùng ô tĩnh (logo nằm dưới đáy)
    def trong_tinh(o):
        return any(o["x1"] >= t["x1"] - 4 and o["x2"] <= t["x2"] + 4 and o["y1"] >= t["y1"] - 4 and o["y2"] <= t["y2"] + 4 for t in o_tinh)
    sub = [(t, o) for t, o in sub if not trong_tinh(o)]
    dai = None
    khoang = []
    if sub:
        y1 = np.percentile([o["y1"] for _, o in sub], 10); y2 = np.percentile([o["y2"] for _, o in sub], 90)
        # Phụ đề Trung căn GIỮA khung ⇒ dải mờ đối xứng quanh tâm, rộng theo dòng dài nhất (p97 nửa bề rộng) + lề 3%
        # (lấy x1/x2 rời nhau thì một bên tràn mép, bên kia cụt, chữ lòi ra).
        cx = W / 2
        nua = np.percentile([max(cx - o["x1"], o["x2"] - cx) for _, o in sub], 97)
        x1, x2 = cx - nua - 0.03 * W, cx + nua + 0.03 * W
        dai = {"x1": int(max(0, x1)), "y1": int(max(0, y1 - 0.012 * H)), "x2": int(min(W, x2)), "y2": int(min(H, y2 + 0.012 * H))}
        giay = sorted({t for t, _ in sub})
        a = b = None
        for t in giay:
            if a is None:
                a = b = t
            elif t - b <= 2:
                b = t
            else:
                khoang.append([max(0, a - 0.6), b + 1.4]); a = b = t
        if a is not None:
            khoang.append([max(0, a - 0.6), b + 1.4])
        # OCR hay sót chữ ngắn/tối ⇒ lỗ mờ. Phụ đề in chết đi cùng lời thoại ⇒ lấy thêm mốc TỪNG CÂU làm khoảng mờ;
        # mờ dải đáy lúc có thoại mà không có chữ thì vô hại (phụ đề Việt đè lên đó).
        for c in (cau or []):
            if c.get("end", 0) - c.get("start", 0) > 0.2:
                khoang.append([max(0, c["start"] - 0.3), c["end"] + 0.6])
        khoang = gop_khoang(khoang)
    # Làm mờ chữ Trung thì chữ Việt phải đè NGAY CHỖ ĐÓ. Phụ đề Trung có lúc DỜI LÊN khỏi dải quen (chú thích, «第N集»…) ⇒ với TỪNG câu:
    # tìm ô chữ Hán đang hiện lúc câu chạy → chữ Việt vẽ đè lên chính ô ấy; không thấy ô nào thì về dải quen.
    vi_tri = {}
    for c in (cau or []):
        trong = [(t, o) for t, o in sub if c["start"] - 0.3 <= t <= c["end"] + 0.3]
        if not trong:
            continue
        # lấy ô ở GIỮA câu làm gốc rồi chỉ gộp ô CHỒNG LÊN nó — gộp hết thì ô của câu kế bên lọt vào, khung bao phình, tâm lệch.
        giua_t = (c["start"] + c["end"]) / 2
        o0 = min(trong, key=lambda x: abs(x[0] - giua_t))[1]
        rx, ry = max(1, o0["x2"] - o0["x1"]), max(1, o0["y2"] - o0["y1"])

        def chong(x):
            return (min(x["x2"], o0["x2"]) - max(x["x1"], o0["x1"]) > 0.4 * rx
                    and min(x["y2"], o0["y2"]) - max(x["y1"], o0["y1"]) > 0.4 * ry)

        nhom = [x for _, x in trong if chong(x)] or [o0]
        o = {"x1": min(x["x1"] for x in nhom), "y1": min(x["y1"] for x in nhom),
             "x2": max(x["x2"] for x in nhom), "y2": max(x["y2"] for x in nhom)}
        # phải gọn trong dải quen theo CẢ HAI trục (chú thích cao đúng tầm phụ đề nhưng sát mép trái vẫn phải đè riêng)
        if dai and o["y1"] >= dai["y1"] - 6 and o["y2"] <= dai["y2"] + 6 and o["x1"] >= dai["x1"] - 10 and o["x2"] <= dai["x2"] + 10:
            continue          # nằm gọn trong dải quen ⇒ vẽ như thường
        vi_tri[c["id"]] = o
    them = []
    if dai:
        ngoai = [(t, o) for t, o in sub if not (o["x1"] >= dai["x1"] - 4 and o["x2"] <= dai["x2"] + 4 and o["y1"] >= dai["y1"] - 4 and o["y2"] <= dai["y2"] + 4)]
        cum = {}
        for t, o in ngoai:   # gom theo vị trí (lưới 3%) — vd «未完待续» góc phải cuối tập
            key = (round(o["x1"] / W * 33), round(o["y1"] / H * 33))
            cum.setdefault(key, []).append((t, o))
        for key, ds in cum.items():
            xs1 = [o["x1"] for _, o in ds]; ys1 = [o["y1"] for _, o in ds]; xs2 = [o["x2"] for _, o in ds]; ys2 = [o["y2"] for _, o in ds]
            gs = sorted({t for t, _ in ds}); kh = []; a = b = None
            for t in gs:
                if a is None: a = b = t
                elif t - b <= 2: b = t
                else: kh.append([max(0, a - 0.6), b + 1.4]); a = b = t
            if a is not None: kh.append([max(0, a - 0.6), b + 1.4])
            them.append({"x1": max(0, min(xs1) - 8), "y1": max(0, min(ys1) - 6), "x2": min(W, max(xs2) + 8), "y2": min(H, max(ys2) + 6),
                         "chu": ds[0][1]["chu"], "khoang": kh})
    return dai, khoang, o_tinh, len(sub), them, vi_tri


def doc_o_tay(f, W, H):
    """them_tay.json → ô hợp lệ, toạ độ kẹp trong khung [0,W]×[0,H]. «khoang» null / không ghi = mờ suốt phim (như ô tĩnh).
    Tệp hỏng / ô sai dạng ⇒ dừng 🔴 (bỏ qua lặng lẽ thì chữ Trung lộ ra); ô nằm hẳn ngoài khung ⇒ bỏ, có log."""
    if not f.exists():
        return []
    try:
        tay = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        sys.exit(f"🔴 05_hinh/them_tay.json không đọc được (JSON hỏng): {str(e)[:120]}")
    if not isinstance(tay, list):
        sys.exit('🔴 05_hinh/them_tay.json phải là danh sách [{"x1","y1","x2","y2","chu","khoang":[[a,b],…] hoặc null}]')
    ra = []
    for i, t in enumerate(tay):
        try:
            x1, x2 = sorted(min(W, max(0, int(float(t[k])))) for k in ("x1", "x2"))
            y1, y2 = sorted(min(H, max(0, int(float(t[k])))) for k in ("y1", "y2"))
            kh = t.get("khoang")
            kh = [[float(a_), float(b_)] for a_, b_ in kh] if kh else None
            if kh and not all(math.isfinite(a_) and math.isfinite(b_) and 0 <= a_ < b_ for a_, b_ in kh):
                raise ValueError("khoang")
        except (AttributeError, KeyError, TypeError, ValueError):
            sys.exit(f"🔴 05_hinh/them_tay.json ô {i + 1}: cần số x1,y1,x2,y2 và «khoang» = [[giây đầu, giây cuối], …] (0 ≤ đầu < cuối) hoặc null")
        if x2 - x1 < 2 or y2 - y1 < 2:
            log(f"⚠️ them_tay.json ô {i + 1}: nằm ngoài khung {W}x{H} — bỏ"); continue
        ra.append({**t, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "khoang": kh})
    return ra


def ve_sub(cau, W, H, thu_muc, dai=None, vi_tri=None):
    from PIL import Image, ImageDraw, ImageFont
    thu_muc.mkdir(exist_ok=True)
    for f in thu_muc.glob("cau_*.png"):   # xoá PNG cũ: câu đã bỏ / hết lời không được sót lại vào bản dựng
        f.unlink()
    goc_co = min(H, W)                        # cỡ chữ theo cạnh NGẮN: video dọc 1080×1920 không bắt đầu ở 92 px
    co0 = int(goc_co * CAU_HINH["sub_ty_le_chu"])
    san_co = min(co0, max(24, int(goc_co * 0.028)))   # co dần tới sàn này nếu câu dài không vừa 2 dòng
    fonts = {}

    def font_co(k):
        if k not in fonts:
            try:
                fonts[k] = ImageFont.truetype(FONT_SUB, k)
            except OSError:
                sys.exit(f"🔴 Không mở được phông phụ đề {FONT_SUB}")
        return fonts[k]
    font_co(co0)
    vien = max(2, int(CAU_HINH["sub_vien_px"] * goc_co / 1080))
    rong_max = int(W * CAU_HINH["sub_rong_toi_da"])
    do = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    def rong(s, font): return do.textbbox((0, 0), s, font=font, stroke_width=vien)[2]

    def bo_dong(s, font):
        tu = s.split(); dong, cur = [], ""
        for w in tu:
            thu = (cur + " " + w).strip()
            if rong(thu, font) <= rong_max or not cur:
                cur = thu
            else:
                dong.append(cur); cur = w
        if cur:
            dong.append(cur)
        return dong

    def xep(s):
        """Cỡ lớn nhất (≤ co0, ≥ san_co) mà lời vừa ≤ 2 dòng, mỗi dòng ≤ rong_max. Không vừa ở sàn ⇒ ép 2 dòng cân nhau ở sàn."""
        for k in range(co0, san_co - 1, -2):
            dong = bo_dong(s, font_co(k))
            if len(dong) <= 2 and all(rong(x, font_co(k)) <= rong_max for x in dong):
                return font_co(k), k, dong
        tu = s.split(); nua = (len(tu) + 1) // 2
        dong = [" ".join(tu[:nua]), " ".join(tu[nua:])] if len(tu) > 1 else tu
        if any(rong(x, font_co(san_co)) > W - 8 for x in dong):
            log(f"⚠️ phụ đề quá dài, vẫn tràn khung ở cỡ {san_co}px: «{s[:50]}» — rút gọn lời trong cau.tsv")
        return font_co(san_co), san_co, dong

    n = 0
    for c in cau:
        if not c.get("vi"):
            continue
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        font, co, dong = xep(c["vi"])
        cao = int(co * 1.18)
        o = (vi_tri or {}).get(c["id"]) or (vi_tri or {}).get(str(c["id"]))
        if o:                      # chữ Trung dời chỗ ⇒ chữ Việt đè lên ĐÚNG ô đã mờ
            yc = (o["y1"] + o["y2"]) / 2; xc = (o["x1"] + o["x2"]) / 2
        elif dai and dai.get("y1") is not None and dai.get("y2") is not None:
            yc = (dai["y1"] + dai["y2"]) / 2; xc = W / 2
        else:
            yc = int(H * CAU_HINH["sub_day"]) - cao * len(dong) / 2; xc = W / 2
        y = int(yc - (cao * len(dong)) / 2)
        y = max(4, min(H - cao * len(dong) - 4, y))   # 2 dòng không được tràn khỏi đáy / đỉnh khung
        for ln in dong:
            r = rong(ln, font)
            x = int(xc - r / 2); x = max(4, min(W - r - 4, x))
            d.text((x, y), ln, font=font, fill=CAU_HINH["sub_mau"], stroke_width=vien, stroke_fill=CAU_HINH["sub_vien"])
            y += cao
        im.save(thu_muc / f"cau_{c['id']:03d}.png", optimize=True)
        n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b5_mo_chu", description="B5 — tìm chữ Trung để làm mờ + vẽ phụ đề Việt PNG")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--chi-sub", action="store_true", help="chỉ vẽ lại phụ đề, không OCR lại")
    a = ap.parse_args(argv)
    d = tap_dir(a.tap)
    goc = d / "01_raw/goc.mp4"
    if not goc.exists():
        sys.exit("🔴 thiếu 01_raw/goc.mp4 — chạy B1 trước")
    cau, doi = doc_cau(d)
    if doi:
        log(f"lời Việt lấy từ cau.tsv: {doi} câu khác cau.json")
    if not cau:
        log("⚠️ chưa có 03_dich/cau.json|cau.tsv — chỉ tìm vùng mờ, không vẽ phụ đề")
    h = d / "05_hinh"
    h.mkdir(exist_ok=True)
    vi = doc_tap(a.tap).get("video") or ffprobe_video(goc)
    W, H = vi["w"], vi["h"]
    t0 = time.time()
    vung = None
    if not a.chi_sub:
        khung, ocr = ocr_khung(goc, h, W, H)
        dai, khoang, o_tinh, so_o, them, vi_tri = phan_tich(ocr, W, H, cau)
        them = list(them) + doc_o_tay(h / "them_tay.json", W, H)
        vung = {"W": W, "H": H, "dai_sub": dai, "khoang": [[round(a_, 2), round(b_, 2)] for a_, b_ in khoang], "tinh": o_tinh,
                "them": them, "vi_tri_sub": {str(k): v for k, v in vi_tri.items()}, "so_khung": len(khung), "so_o_sub": so_o}
        ghi_json(h / "vung_mo.json", vung)
        log(f"dải sub: {dai} · {len(khoang)} khoảng có chữ · {len(o_tinh)} ô tĩnh: {[t['chu'] for t in o_tinh]} · "
            f"{len(them)} ô thêm: {[t.get('chu') for t in them]}")
    else:
        vung = doc_json(h / "vung_mo.json")
        if not vung:
            log("⚠️ chưa có vung_mo.json — phụ đề vẽ ở đáy mặc định")
    dai = (vung or {}).get("dai_sub")
    n = ve_sub(cau, W, H, h / "sub_png", dai=dai, vi_tri=(vung or {}).get("vi_tri_sub"))
    log(f"vẽ {n} PNG phụ đề · {time.time() - t0:.0f}s")
    xong_buoc(a.tap, "b5_mo_chu", so_sub_png=n, giay=round(time.time() - t0))


if __name__ == "__main__":
    main()
