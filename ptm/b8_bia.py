"""B8 — TIÊU ĐỀ + BÌA MỚI (không chép của nguồn). Máy chọn khung, trợ lý viết chữ, người dùng chốt — không tự đăng.

1. Bìa: chấm mọi khung 1 hình/giây (05_hinh/khung) theo độ nét × độ màu, trừ khung có chữ Trung in chết, chọn 6 khung cách nhau
   ≥ 5 s, rút lại ở cỡ gốc → `08_dang/bia_ungvien/bia_N_<giây>s.png`.
2. Chữ: `08_dang/de_xuat.json` chưa có tiêu đề / chữ bìa ⇒ phiếu `08_dang/CAN_TIEU_DE.json` (luật viết + ảnh ứng viên cần xem), thoát mã 3.
3. Vẽ: bìa 1280×720 chữ vàng viền đen (mờ chữ Trung trước) → `bia_final.png`, ghi `bai_dang.json`. Video DỌC: giữ trọn khung bên phải,
   chữ bên trái (không cắt ngang giữa) + thêm `bia_doc.png` 1080×1920 cho Shorts.

    python -m ptm.b8_bia --tap <slug>                                  # ứng viên + phiếu / vẽ theo de_xuat.json
    python -m ptm.b8_bia --tap <slug> --chon 3 --chu "DÒNG 1|DÒNG 2" [--tieu-de 2]
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

from .chung import CJK, FONT_BIA, can, chay, cho_tro_ly, doc_cau, doc_json, doc_tap, ffprobe_dur, ghi_json, goc_du_an, log, tap_dir, xong_buoc

LUAT_TIEU_DE = [
    "Tiêu đề có dạng «<Tên phim tiếng Việt> – <ý ngắn>» (máy tự ghép nếu chỉ điền ten_bo_viet + y_ngan). Tổng ≤ 70 ký tự.",
    "Viết 3 phương án «y_ngan»: mỗi cái 4–8 từ (≤ 38 ký tự), KHÔNG lặp tên phim, nói đúng MỘT chuyện đáng tò mò nhất CÓ THẬT trong tập.",
    "Chữ người thường (trẻ 5 tuổi) hiểu ngay; KHÔNG chữ Hán, KHÔNG pinyin; tên riêng Hán-Việt; không viết hoa toàn bộ; không emoji; không dấu chấm cuối.",
    "Ví dụ tốt: «Bé cương thi đòi nhận chị», «Nhặt được kẻ thù từ trên trời rơi xuống». Ví dụ xấu (dài, kể lể): «Vào sàn đấu giá lấy trâm ngọc, cô gái bị cương thi bám theo gọi chị».",
    "ten_bo_viet: tên phim Hán-Việt; bộ đã có tên ở tập trước thì dùng đúng tên đó.",
    "mo_ta: 2–3 câu tiếng Việt kể nội dung tập, không hứa điều video không có; dòng cuối ghi tác giả gốc + link video gốc (tap.json «tac_gia», «nguon»), vd «Nguồn: <tác giả> trên Douyin — <link>». tags: đúng 8 tag.",
    "Xem 6 ảnh ứng viên, chọn MỘT («chon_bia» = số stt): thấy trọn mặt nhân vật chính (không bị mép cắt, nhìn máy hoặc 3/4), nét, cảm xúc rõ, "
    "sáng và màu nổi, nửa dưới còn chỗ cho 2 dòng chữ. Loại: mặt bị cắt, quay lưng, không người, tối, nhoè, có chữ phụ đề lớn giữa hình.",
    "chu_bia: 2 dòng cách bằng «|», thường là «TÊN PHIM|Ý NGẮN» viết hoa, cùng ý với tiêu đề 1.",
]


def ten_bo_da_co(cot_loi):
    return (doc_json(goc_du_an() / "ten_bo_viet.json") or {}).get(cot_loi or "", "")


def ghi_ten_bo(cot_loi, ten):
    if not cot_loi or not ten:
        return
    f = goc_du_an() / "ten_bo_viet.json"
    bang = doc_json(f) or {}
    if not bang.get(cot_loi):
        bang[cot_loi] = ten; ghi_json(f, bang); log(f"bộ mới: ghi tên Việt «{ten}» vào {f.name}")


def tua_goc(d, t):
    """Tựa video gốc: B1 ghi nguon.tieu_de (bản cũ ghi «tua»); không có thì lấy «tua» của B0 (00_do_trung/do_trung.json)."""
    ng = t.get("nguon") or {}
    return ng.get("tieu_de") or ng.get("tua") or (doc_json(d / "00_do_trung/do_trung.json") or {}).get("tua") or ""


def anh_trong_tap(p, d):
    """Đường dẫn ảnh ghi trong de_xuat.json phải là đường TƯƠNG ĐỐI nằm trong thư mục tập (cấm tuyệt đối, cấm «..» ra ngoài)."""
    p = str(p or "")
    if not p or Path(p).is_absolute():
        sys.exit(f"🔴 de_xuat.json: ảnh «{p}» phải là đường tương đối trong thư mục tập (vd 08_dang/bia_ungvien/bia_1_8s.png)")
    f = (d / p).resolve()
    try:
        f.relative_to(d.resolve())
    except ValueError:
        sys.exit(f"🔴 de_xuat.json: ảnh «{p}» trỏ ra ngoài thư mục tập — không dùng")
    if not f.is_file():
        sys.exit(f"🔴 de_xuat.json: không thấy ảnh «{p}» — chạy lại: python -m ptm.b8_bia --tap {d.name} --lai-ung-vien")
    return f


def ds_chu(de, khoa):
    """Trường chữ của de_xuat.json: chuỗi hoặc danh sách chuỗi → [chuỗi] đã bỏ khoảng trắng, bỏ dòng rỗng. Kiểu khác ⇒ 🔴."""
    v = de.get(khoa)
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        sys.exit(f"🔴 de_xuat.json: «{khoa}» phải là chuỗi hoặc danh sách chuỗi (đang là {json.dumps(v, ensure_ascii=False)[:80]})")
    return [x.strip() for x in v if x.strip()]


def soat_bia(ds):
    """Ứng viên bìa phải có stt (số), giay (số), file (chuỗi) — thiếu thì dừng, bảo làm lại ứng viên."""
    for i, b in enumerate(ds, 1):
        ok = isinstance(b, dict) and isinstance(b.get("stt"), int) and isinstance(b.get("giay"), (int, float)) \
            and not isinstance(b.get("giay"), bool) and isinstance(b.get("file"), str)
        if not ok:
            sys.exit(f"🔴 de_xuat.json: ứng viên bìa thứ {i} thiếu / sai «stt», «giay», «file» — chạy lại với --lai-ung-vien")


def ghep_tieu_de(ten_phim, y):
    y = y.strip().rstrip(".!…").strip(); y = y[:1].upper() + y[1:]
    return f"{ten_phim} – {y}" if ten_phim else y


def cham_khung(khung_dir, ocr):
    import cv2, numpy as np
    co_chu = {k["t"] for k in (ocr or []) if k["o"]}
    diem = []
    for f in sorted(khung_dir.glob("*.jpg")):
        t = int(f.stem) - 1
        im = cv2.imread(str(f))
        if im is None:
            continue
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        net = cv2.Laplacian(g, cv2.CV_64F).var()
        b, gg, r = cv2.split(im.astype("float"))
        rg, yb = r - gg, 0.5 * (r + gg) - b
        mau = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
        sang = g.mean()
        d = (net ** 0.5) * (mau ** 0.7) * (1.0 if 40 < sang < 215 else 0.4) * (0.35 if t in co_chu else 1.0)
        diem.append((d, t, f))
    diem.sort(reverse=True)
    chon = []
    for d, t, f in diem:
        if all(abs(t - c[1]) >= 5 for c in chon):
            chon.append((d, t, f))
        if len(chon) == 6:
            break
    return chon


def rut_goc(goc, giay, ra, dur):
    """Rút một khung cỡ gốc ở giay+0,5 (kẹp ≤ dur−0,5 để khung cuối không ra rỗng). Trả True nếu có ảnh."""
    ra.unlink(missing_ok=True)
    tt = min(max(0.0, dur - 0.5), giay + 0.5)
    subprocess.run([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-ss", f"{tt:.2f}", "-i", str(goc), "-frames:v", "1", str(ra)], check=True)
    return ra.is_file() and ra.stat().st_size > 0


def mo_chu_trung(im, vung, giay=None, W=1280, H=720):
    """Mờ chữ Trung (phụ đề + logo) NGAY TRÊN KHUNG GỐC, trước khi co / cắt / dàn trang. vung_mo.json ghi toạ độ theo khung gốc (vung["W"]);
    lề và độ mờ tính theo cỡ bìa 16:9 như bản trước (nhân hệ số co ngược) ⇒ bìa ngang ra như cũ, bìa dọc dùng chung một chỗ mờ."""
    from PIL import ImageFilter
    if not vung:
        return im
    tv = im.width / vung["W"] if vung.get("W") else 1.0                 # toạ độ vung → điểm ảnh của ảnh đang có
    nguoc = 1 / max(W / im.width, H / im.height)                        # 1 điểm bìa 16:9 = bao nhiêu điểm khung gốc
    o_ds = ([("dai", vung["dai_sub"])] if vung.get("dai_sub") else []) + [("o", o) for o in vung.get("tinh") or []] + [
        ("o", o) for o in vung.get("them") or []   # ô «them» chỉ mờ khi khung bìa nằm trong khoảng của nó
        if giay is None or not o.get("khoang") or any(a0 - 1 <= giay <= b0 + 1 for a0, b0 in o["khoang"])]
    for loai, o in o_ds:
        lx, ly = (40, 10) if loai == "dai" else (15, 10)
        box = (max(0, int(o["x1"] * tv - lx * nguoc)), max(0, int(o["y1"] * tv - ly * nguoc)),
               min(im.width, int(o["x2"] * tv + lx * nguoc)), min(im.height, int(o["y2"] * tv + ly * nguoc)))
        if box[2] > box[0] and box[3] > box[1]:
            im.paste(im.crop(box).filter(ImageFilter.GaussianBlur(radius=max(6, 20 * nguoc))), box)
    return im


def phu_kin(im, W, H):
    """Co cho phủ kín W×H rồi cắt GIỮA (nguồn 21:9 hay 9:16 không bị lệch về góc trái trên)."""
    ty = max(W / im.width, H / im.height)
    rw, rh = int(im.width * ty) + 1, int(im.height * ty) + 1
    ox, oy = (rw - W) // 2, (rh - H) // 2
    return im.resize((rw, rh)).crop((ox, oy, ox + W, oy + H))


def ngat_deu(ln, do, rong):
    """Ngắt một dòng thành ÍT hàng nhất vừa `rong`, các hàng dài gần bằng nhau («MÂY GIÔNG | BÁO NGUY», không sót một chữ xuống hàng)."""
    import itertools
    tu = ln.split()
    for r in range(1, len(tu) + 1):
        tot = None
        for cat in itertools.combinations(range(1, len(tu)), r - 1):
            mien = [0, *cat, len(tu)]
            hang = [" ".join(tu[a:b]) for a, b in zip(mien, mien[1:])]
            dai = max(do(h) for h in hang)
            if dai <= rong and (tot is None or dai < tot[0]):
                tot = (dai, hang)
        if tot:
            return tot[1]
        if r >= 4:
            break
    return [ln]   # một chữ dài hơn cả bề rộng: để vòng ngoài thu cỡ


def viet_chu(im, dong, x0, y_day, rong, co_dau, co_min=48, cao_toi_da=None, giua_doc=None):
    """Chữ vàng viền đen. Dòng dài quá bề rộng thì NGẮT theo từ (không thu chữ tới mức khó đọc); vẫn không vừa thì thu cỡ.
    Đặt đáy khối chữ ở y_day, hoặc giữa khối chữ ở giua_doc."""
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(im)
    rong_dong = lambda f: max(d.textbbox((0, 0), ln, font=f)[2] for ln in dong)
    co = co_dau   # trước hết thu chữ tới 3/4 cỡ để mỗi dòng giữ trọn trên một hàng (khỏi ngắt «TIỂU | NỮ», sót một chữ xuống hàng)
    while co - 6 >= max(co_min, int(co_dau * 0.75)) and rong_dong(ImageFont.truetype(FONT_BIA, co)) > rong:
        co -= 6
    if rong_dong(ImageFont.truetype(FONT_BIA, co)) > rong:
        co = co_dau
    while True:
        font = ImageFont.truetype(FONT_BIA, co)
        hang = []
        for ln in dong:
            hang += ngat_deu(ln, lambda x: d.textbbox((0, 0), x, font=font)[2], rong)
        lh = int(co * 1.15)
        vua = all(d.textbbox((0, 0), h, font=font)[2] <= rong for h in hang) and (cao_toi_da is None or lh * len(hang) <= cao_toi_da)
        if vua or co <= co_min:
            break
        co -= 6
    vien = max(5, round(co * 0.08))
    y = (giua_doc - lh * len(hang) // 2) if giua_doc is not None else (y_day - lh * len(hang))
    for h in hang:
        d.text((x0, y), h, font=font, fill="#FFF200", stroke_width=vien, stroke_fill="#000000")
        y += lh
    return im


def day_toi(im, tu=0.5, manh=200):
    """Dải tối từ `tu` (tỉ lệ chiều cao) xuống đáy để chữ nổi."""
    from PIL import Image, ImageDraw
    W, H = im.size
    lop = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lop)
    y0 = int(H * tu)
    for y in range(y0, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(manh * (y - y0) / max(1, H - y0))))
    return Image.alpha_composite(im.convert("RGBA"), lop)


LA_DOC = 1.2   # khung gốc rộng/cao dưới mức này (dọc, vuông) ⇒ không cắt ngang giữa (27/11/2026: tập thử dọc bị cắt mất đám mây trên đầu bé)


def ve_bia(anh, chu, ra, vung=None, giay=None, ra_doc=None):
    """Bìa 1280×720. Khung NGANG: phủ kín + cắt giữa, chữ ở đáy (như cũ). Khung DỌC / vuông: giữ TRỌN khung ở bên phải trên nền chính nó
    phóng to làm mờ, chữ to ở bên trái — không cắt mất đầu, mặt hay thứ ở trên đầu nhân vật. Có `ra_doc` thì vẽ thêm bìa 1080×1920 (Shorts)."""
    from PIL import Image, ImageFilter, ImageEnhance
    dong = [s.strip() for s in chu.split("|") if s.strip()][:2]   # main() đã soát chu có dòng chữ
    im = mo_chu_trung(Image.open(anh).convert("RGB"), vung, giay)
    W, H = 1280, 720
    doc = im.width / im.height < LA_DOC
    if not doc:
        bia = day_toi(phu_kin(im, W, H))
        viet_chu(bia, dong, 40, H - 40, W - 80, 118 if len(dong) == 1 else 100)
    else:
        nen = phu_kin(im, W, H).filter(ImageFilter.GaussianBlur(radius=28))
        nen = ImageEnhance.Brightness(nen).enhance(0.55)
        cao = H - 40
        rong = min(int(im.width * cao / im.height), int(W * 0.5))
        cao = int(im.height * rong / im.width)
        truoc = im.resize((rong, cao))
        x = W - rong - 40
        y = (H - cao) // 2
        bia = nen.convert("RGBA")
        bong = Image.new("RGBA", (rong + 16, cao + 16), (0, 0, 0, 150)).filter(ImageFilter.GaussianBlur(6))
        bia.alpha_composite(bong, (x - 4, y + 2))
        bia.paste(Image.new("RGB", (rong + 8, cao + 8), "#FFFFFF"), (x - 4, y - 4))
        bia.paste(truoc, (x, y))
        viet_chu(bia, dong, 48, None, x - 48 - 40, 112, co_min=56, cao_toi_da=H - 80, giua_doc=H // 2)
    bia.convert("RGB").save(ra, quality=92)
    if ra_doc and doc:
        WD, HD = 1080, 1920
        bd = day_toi(phu_kin(im, WD, HD), tu=0.55, manh=210)
        viet_chu(bd, dong, 50, HD - 260, WD - 100, 120, co_min=64)   # chừa ~260 đáy cho nút / tên kênh của Shorts
        bd.convert("RGB").save(ra_doc, quality=92)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b8_bia", description="B8 — tiêu đề + bìa")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--chon", type=int, help="số thứ tự khung bìa (1–6); mặc định chon_bia trong de_xuat.json")
    ap.add_argument("--chu", help="chữ trên bìa, 2 dòng cách bằng |; mặc định chu_bia trong de_xuat.json")
    ap.add_argument("--tieu-de", type=int, help="số thứ tự tiêu đề (1–3), mặc định 1")
    ap.add_argument("--lai-ung-vien", action="store_true", help="chấm lại khung, rút lại 6 ảnh ứng viên")
    a = ap.parse_args(argv)
    can("ffmpeg")
    d = tap_dir(a.tap)
    t = doc_tap(a.tap)
    dd = d / "08_dang"; (dd / "bia_ungvien").mkdir(parents=True, exist_ok=True)
    f_de = dd / "de_xuat.json"
    try:
        de = json.loads(f_de.read_text(encoding="utf-8")) if f_de.exists() else {}
    except (OSError, UnicodeDecodeError, ValueError) as e:
        sys.exit(f"🔴 08_dang/de_xuat.json không đọc được (JSON hỏng): {str(e)[:120]} — sửa tệp, hoặc xoá để máy làm lại ứng viên bìa")
    if not isinstance(de, dict):
        sys.exit("🔴 08_dang/de_xuat.json phải là object JSON {…} (các trường bia, ten_bo_viet, y_ngan, chu_bia, chon_bia…)")
    if de.get("bia") is not None and not isinstance(de["bia"], list):
        sys.exit("🔴 08_dang/de_xuat.json: «bia» phải là danh sách ứng viên — xoá trường này để máy làm lại")
    goc = d / "01_raw/goc.mp4"

    # 1. ứng viên bìa
    if a.lai_ung_vien or not de.get("bia"):
        if not goc.exists():
            sys.exit(f"🔴 thiếu 01_raw/goc.mp4 — chạy B1 trước: python -m ptm nhan --tap {a.tap} …")
        kd = d / "05_hinh/khung"
        if not any(kd.glob("*.jpg")):
            kd.mkdir(parents=True, exist_ok=True)
            chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", goc, "-vf", "fps=1,scale=960:-2", "-q:v", "5", kd / "%05d.jpg"])
        chon = cham_khung(kd, doc_json(d / "05_hinh/ocr_khung.json"))
        for f in (dd / "bia_ungvien").glob("*.png"):
            f.unlink()
        de["bia"] = []
        dur = ffprobe_dur(goc)
        for diem, giay, _ in chon:
            i = len(de["bia"]) + 1
            ra = dd / "bia_ungvien" / f"bia_{i}_{giay}s.png"
            if not rut_goc(goc, giay, ra, dur):
                log(f"⚠️ không rút được khung {giay}s — bỏ ứng viên này"); continue
            de["bia"].append({"stt": i, "giay": giay, "file": str(ra.relative_to(d)), "diem": round(float(diem), 1)})
        if not de["bia"]:
            sys.exit("🔴 Không rút được khung bìa ứng viên nào từ 01_raw/goc.mp4")
        ghi_json(f_de, de)
        log(f"{len(de['bia'])} khung bìa ứng viên → {dd / 'bia_ungvien'}")

    soat_bia(de["bia"])

    # 2. chữ: trợ lý điền ten_bo_viet + y_ngan (máy ghép tiêu đề) hoặc tieu_de; chu_bia. Rỗng hết = coi như chưa có ⇒ phiếu.
    if de.get("ten_bo_viet") is not None and not isinstance(de["ten_bo_viet"], str):
        sys.exit("🔴 de_xuat.json: «ten_bo_viet» phải là chuỗi")
    for khoa in ("y_ngan", "tieu_de"):
        v = ds_chu(de, khoa)
        if v:
            de[khoa] = v
        else:
            de.pop(khoa, None)
    ten_v = (de.get("ten_bo_viet") or "").strip() or ten_bo_da_co(t.get("cot_loi"))
    if de.get("y_ngan"):
        goc_td = {"y_ngan": de["y_ngan"], "ten_bo_viet": ten_v}   # tiêu đề máy ghép từ y_ngan nào — y_ngan / tên đổi thì ghép lại
        moi = [ghep_tieu_de(ten_v, y) for y in de["y_ngan"]][:3]
        td_cu = de.get("tieu_de") if isinstance(de.get("tieu_de"), list) else []
        # tệp cũ chưa có «tieu_de_tu»: tiêu đề đủ số và cùng tên phim, hoặc cùng ý ngắn ⇒ là bản máy ghép trước đây
        cung_ten = bool(ten_v) and all(x.startswith(f"{ten_v} – ") for x in td_cu)
        cung_y = all(x.split(" – ", 1)[-1] == m.split(" – ", 1)[-1] for x, m in zip(td_cu, moi))
        may_ghep = bool(td_cu) and len(td_cu) == len(moi) and (cung_ten or cung_y)
        if de.get("tieu_de_tu"):
            ghep_lai = not de.get("tieu_de") or de["tieu_de_tu"] != goc_td
        else:
            ghep_lai = not de.get("tieu_de") or (may_ghep and td_cu != moi)
        if ghep_lai:
            if de.get("tieu_de"):
                log("y_ngan / ten_bo_viet đã đổi ⇒ ghép lại tiêu đề")
            de["tieu_de"] = moi
            de["tieu_de_tu"] = goc_td
    if not de.get("tieu_de") or not (a.chu or de.get("chu_bia")):
        cau, _ = doc_cau(d)
        cho_tro_ly(dd / "CAN_TIEU_DE.json", "Viết tiêu đề, mô tả, tag, chữ bìa và chọn khung bìa",
                   luat=LUAT_TIEU_DE, thu_muc_tap=str(d),
                   ghi_vao="08_dang/de_xuat.json — thêm các trường: ten_bo_viet, y_ngan [3], mo_ta, tags [8], chu_bia, chon_bia (giữ nguyên trường «bia»)",
                   lenh_tiep=f"python -m ptm.b8_bia --tap {a.tap}",
                   ten_bo_goc=t.get("cot_loi") or "", ten_bo_viet_da_co=ten_v,
                   tua_goc=tua_goc(d, t)[:150],
                   loi_thoai=" / ".join(c["vi"] for c in cau[:80] if c.get("vi"))[:3000],
                   anh_ung_vien=[{"stt": b["stt"], "giay": b["giay"], "anh": b["file"]} for b in de["bia"]])
    (dd / "CAN_TIEU_DE.json").unlink(missing_ok=True)
    if de.get("ten_bo_viet"):
        ghi_ten_bo(t.get("cot_loi"), de["ten_bo_viet"])
    ghi_json(f_de, de)

    # 3. vẽ bìa + gói đăng
    try:
        so_bia = a.chon if a.chon is not None else int(de["chon_bia"]) if de.get("chon_bia") is not None else 1
    except (TypeError, ValueError):
        sys.exit(f"🔴 de_xuat.json: chon_bia «{de.get('chon_bia')}» phải là số thứ tự khung (1–{len(de['bia'])})")
    b = next((x for x in de["bia"] if isinstance(x, dict) and x.get("stt") == so_bia), None)
    if not b:
        sys.exit(f"🔴 Khung {so_bia} không có trong de_xuat.json (có {[x.get('stt') for x in de['bia'] if isinstance(x, dict)]})")
    chu = a.chu if a.chu is not None else de.get("chu_bia")
    dong_chu = [x.strip() for x in chu.split("|") if x.strip()] if isinstance(chu, str) else []
    if not dong_chu:
        sys.exit(f"🔴 chữ bìa «{chu}» rỗng — cần 1–2 dòng chữ cách bằng «|» (chu_bia trong de_xuat.json hoặc --chu)")
    if len(dong_chu) > 2:
        log(f"⚠️ chữ bìa có {len(dong_chu)} dòng — chỉ vẽ 2 dòng đầu")
    chu = "|".join(dong_chu[:2])
    so_td = a.tieu_de if a.tieu_de is not None else 1
    if not 1 <= so_td <= len(de["tieu_de"]):
        sys.exit(f"🔴 --tieu-de {so_td} không có (có {len(de['tieu_de'])} tiêu đề)")
    td = de["tieu_de"][so_td - 1]
    canh = []
    if len(td) > 70:
        canh.append(f"tiêu đề {len(td)} ký tự > 70")
    if CJK.search(td + chu):
        canh.append("tiêu đề / chữ bìa còn chữ Hán")
    anh = anh_trong_tap(b.get("file"), d)
    (dd / "bia_doc.png").unlink(missing_ok=True)
    doc = ve_bia(anh, chu, dd / "bia_final.png", vung=doc_json(d / "05_hinh/vung_mo.json"), giay=b["giay"], ra_doc=dd / "bia_doc.png")
    ghi_json(dd / "bai_dang.json", {"tieu_de": td, "mo_ta": de.get("mo_ta"), "tags": de.get("tags"), "bia": "08_dang/bia_final.png",
                                    **({"bia_doc": "08_dang/bia_doc.png"} if doc else {}),
                                    "video": f"07_out/{a.tap}_final.mp4", "khung_bia_giay": b["giay"], "chu_bia": chu,
                                    "chot": time.strftime("%Y-%m-%d %H:%M")})
    log(f"bìa: {dd / 'bia_final.png'}" + (f" + bìa dọc cho Shorts {dd / 'bia_doc.png'}" if doc else "") + f" · tiêu đề: {td}"
        + (f" · ⚠️ {'; '.join(canh)}" if canh else ""))
    xong_buoc(a.tap, "b8_bia", co_bia_final=True, so_tieu_de=len(de["tieu_de"]), canh_bao=canh)


if __name__ == "__main__":
    main()
