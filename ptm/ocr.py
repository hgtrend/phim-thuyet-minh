"""Đọc chữ Hán trên hình (RapidOCR, chạy tại máy) — dùng chung cho B3 (bù câu tai không nghe ra) và B5 (tìm vùng làm mờ).

Khung rút 1 hình/giây, rộng 960 → `05_hinh/khung/%05d.jpg`; kết quả → `05_hinh/ocr_khung.json`
= [{"t": giây, "o": [{x1,y1,x2,y2 (toạ độ khung GỐC), chu, sc}]}]. Có sẵn và đủ khung thì đọc lại, không OCR lại.
"""
import subprocess, sys

from .chung import CJK, can, chay, doc_json, ghi_json, log

RONG_OCR = 960


def may_ocr():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        sys.exit("🔴 Thiếu bộ đọc chữ: «pip install rapidocr_onnxruntime»")
    return RapidOCR()


def rut_khung(goc, kd):
    kd.mkdir(parents=True, exist_ok=True)
    if not any(kd.glob("*.jpg")):
        chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", goc, "-vf", f"fps=1,scale={RONG_OCR}:-2",
              "-q:v", "5", kd / "%05d.jpg"])
    return sorted(kd.glob("*.jpg"))


def ocr_tat_ca(khung, W, H):
    ocr = may_ocr()
    ty = W / RONG_OCR
    ra = []
    for i, f in enumerate(khung):
        res, _ = ocr(str(f))
        o = []
        for box, txt, sc in (res or []):
            if not CJK.search(txt) or float(sc) < 0.45:
                continue
            x1, y1 = box[0]; x2, y2 = box[2]
            o.append({"x1": int(x1 * ty), "y1": int(y1 * ty), "x2": int(x2 * ty), "y2": int(y2 * ty), "chu": txt, "sc": round(float(sc), 2)})
        ra.append({"t": i, "o": o})
        if i % 60 == 0:
            log(f"OCR khung {i}/{len(khung)}")
    return ra


def ocr_khung(goc, h, W, H):
    """Rút khung + OCR (có cache) → (danh sách khung, ocr)."""
    khung = rut_khung(goc, h / "khung")
    ocr = doc_json(h / "ocr_khung.json")
    if not ocr or len(ocr) != len(khung):
        ocr = ocr_tat_ca(khung, W, H)
        ghi_json(h / "ocr_khung.json", ocr)
    return khung, ocr


def ocr_giua_cau(goc, cau, W, H, thu_muc):
    """Đọc dòng phụ đề in chết (đáy khung, y > 72%) tại GIỮA mỗi câu — khung rộng 1280 — → [chuỗi] cùng thứ tự cau."""
    ocr = may_ocr()
    ffmpeg = can("ffmpeg")
    thu_muc.mkdir(parents=True, exist_ok=True)
    ra = []
    for i, c in enumerate(cau):
        mid = (c["start"] + c["end"]) / 2
        f = thu_muc / f"{i:04d}.jpg"
        f.unlink(missing_ok=True)   # khung cũ của lượt trước không được đọc nhầm khi ffmpeg không ra khung
        # không check: mốc sát cuối phim có thể không ra khung — câu đó để rỗng
        subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", "-ss", f"{mid:.2f}", "-i", str(goc),
                        "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "4", str(f)])
        chu = ""
        if f.exists():
            res, _ = ocr(str(f))
            dong = []
            for box, txt, sc in (res or []):
                yc = (box[0][1] + box[2][1]) / 2 / (H * 1280 / W)
                if CJK.search(txt) and float(sc) >= 0.5 and yc > 0.72:
                    dong.append((box[0][1], txt))
            chu = " ".join(t for _, t in sorted(dong))
        ra.append(chu)
        if i % 25 == 0:
            log(f"OCR {i}/{len(cau)}")
    return ra
