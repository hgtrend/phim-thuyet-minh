"""KIỂM TẬP — cổng máy tất định, chạy sau B8 và TRƯỚC khi đăng. Không cần model.

Mỗi mục có điều kiện đạt rõ. Ra `07_out/KIEM.md` + `KIEM.json`; thoát mã 1 nếu có mục 🔴.
Mức: OK · 🟡 nhắc (không chặn) · 🔴 chặn. Xin phép tác giả chỉ nhắc, không bao giờ chặn.

    python -m ptm.kiem --tap <slug> [--truoc-dang]
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

from .chung import CAU_HINH, CJK, can, doc_cau, doc_json, doc_tap, ffprobe_dur, ffprobe_video, tap_dir

XIN_PHEP = {"chua_gui": "chưa gửi thư xin phép", "da_gui": "đã gửi, chưa có trả lời", "dong_y": "tác giả đồng ý",
            "tu_choi": "tác giả TỪ CHỐI — đăng là tự chịu rủi ro bản quyền"}


def lufs(f):
    p = subprocess.run([can("ffmpeg"), "-hide_banner", "-v", "info", "-i", str(f), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    bang = [b for b in re.findall(r"\{[^{}]+\}", p.stderr) if '"input_i"' in b]   # bảng đo loudnorm là khối CUỐI
    return json.loads(bang[-1]) if bang else {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.kiem", description="Kiểm tập trước khi đăng")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--truoc-dang", action="store_true", help="chạy ngay trước khi đăng: thiếu tiêu đề / bìa là 🔴 (mặc định 🟡)")
    a = ap.parse_args(argv)
    d = tap_dir(a.tap); t = doc_tap(a.tap)
    R = []   # (mức, tên, chi tiết)

    def ok(ten, dk, chi_tiet, canh_bao=False):
        R.append(("OK" if dk else ("🟡" if canh_bao else "🔴"), ten, chi_tiet))

    # 1. Dò trùng (B0 không bắt buộc): chưa chạy = 🟡; đã chạy mà ĐỎ (đã có bản Việt trùng) = 🔴
    muc = t.get("do_trung") or ((t.get("buoc") or {}).get("b0_do_trung") or {}).get("muc")
    ok("B0 dò trùng đã chạy", muc in ("xanh", "vang", "do"), f"muc={muc or 'chưa chạy'}", canh_bao=True)
    if muc:
        ok("B0 không ĐỎ", muc != "do", f"muc={muc} (ĐỎ = đã có bản Việt trùng ⇒ không nên đăng)")
    # 1b. Xin phép tác giả — chỉ nhắc
    xp = (t.get("xin_phep") or {}).get("trang_thai") or "chua_gui"
    ok("xin phép tác giả", xp == "dong_y", XIN_PHEP.get(xp, xp) + ("" if xp == "dong_y" else f" · python -m ptm.xin_phep --tap {a.tap}"), canh_bao=True)
    # 2. Nguồn + bản cuối
    goc, final = d / "01_raw/goc.mp4", d / "07_out" / f"{a.tap}_final.mp4"
    ok("có goc.mp4 + final.mp4", goc.exists() and final.exists(), f"{goc.exists()} / {final.exists()}")
    if goc.exists() and final.exists():
        dg, df = ffprobe_dur(goc), ffprobe_dur(final)
        ok("thời lượng final = gốc (±0,15 s)", abs(dg - df) <= 0.15, f"gốc {dg:.2f} · final {df:.2f}")
        vg, vf = ffprobe_video(goc), ffprobe_video(final)
        ok("khung hình giữ nguyên", (vg["w"], vg["h"]) == (vf["w"], vf["h"]), f"{vg['w']}x{vg['h']} → {vf['w']}x{vf['h']}")
        ln = lufs(final)
        li, tp = float(ln.get("input_i", -99)), float(ln.get("input_tp", 0))
        ok(f"loudness {CAU_HINH['lufs']:g} LUFS ±1", abs(li - CAU_HINH["lufs"]) <= 1.0, f"{li:.1f} LUFS")
        ok("true peak ≤ −1 dBTP", tp <= -1.0, f"{tp:.1f} dBTP")
    # 3. Câu + lời
    cau, _ = doc_cau(d)
    ok("có câu dịch", len(cau) > 0, f"{len(cau)} câu")
    rong = [c["id"] for c in cau if not c.get("vi")]
    ok("mọi câu có lời Việt", not rong, f"thiếu: {rong[:10]}")
    han = [c["id"] for c in cau if CJK.search(c.get("vi", ""))]
    ok("lời Việt không lẫn chữ Hán", not han, f"câu: {han[:10]}")
    # chỉ dấu macron/caron của pinyin — á à é è… là dấu tiếng Việt
    pinyin = [c["id"] for c in cau if re.search(r"[āǎēěīǐōǒūǔǖǘǚǜ]", c.get("vi", ""))]
    ok("không pinyin", not pinyin, f"câu: {pinyin[:10]}")
    vuot = [c["id"] for c in cau if len((c.get("vi") or "").split()) > c.get("ngan_sach", 999) + 3]   # đếm từ trên lời hiện tại, không tin so_tu cũ
    ok("số từ trong ngân sách (+3)", not vuot, f"vượt: {vuot[:10]}", canh_bao=True)
    # 4. Giọng khớp khe
    khop = doc_json(d / "04_giong/khop.json") or []
    ok("có khop.json", bool(khop), f"{len(khop)} câu")
    xau = [k["id"] for k in khop if k.get("trang_thai") in ("VAN_DAI", "KHONG_LOI")]
    cung = [k["id"] for k in khop if k.get("trang_thai") == "NEN_CUNG"]
    ok("không câu nào VẪN DÀI / không lời", not xau, f"câu: {xau[:10]}")
    ok("nén cứng (>1,10×) ≤ 5% số câu", len(cung) <= max(1, len(cau) * 0.05), f"{len(cung)} câu: {cung[:10]}", canh_bao=True)
    gv = d / "04_giong/giong_viet.wav"
    ok("có giong_viet.wav", gv.exists(), gv.name)
    # 5. Mờ chữ + phụ đề
    vung = doc_json(d / "05_hinh/vung_mo.json") or {}
    ocr = doc_json(d / "05_hinh/ocr_khung.json") or []
    dai = vung.get("dai_sub")
    H = vung.get("H") or (ffprobe_video(goc)["h"] if goc.exists() else None)   # thiếu vung_mo ⇒ chiều cao THẬT của video
    o_sub = [(k.get("t", 0), o) for k in ocr for o in (k.get("o") or []) if H and (o["y1"] + o["y2"]) / 2 / H > 0.72]

    def trong_o(o, v):
        return o["x1"] >= v["x1"] - 4 and o["x2"] <= v["x2"] + 4 and o["y1"] >= v["y1"] - 4 and o["y2"] <= v["y2"] + 4

    def trong_kh(t, kh):   # kh None/rỗng = mờ suốt phim
        return not kh or any(a_ - 0.5 <= t <= b_ + 0.5 for a_, b_ in kh)

    def phu(t, o):   # ô chữ lúc t bị làm mờ: trong dải sub ĐÚNG lúc dải bật, trong ô tĩnh, hoặc trong ô «them» đúng khoảng của nó
        return ((dai and trong_o(o, dai) and vung.get("khoang") and trong_kh(t, vung["khoang"]))
                or any(trong_o(o, v) for v in vung.get("tinh") or [])
                or any(trong_o(o, v) and trong_kh(t, v.get("khoang")) for v in vung.get("them") or []))
    if o_sub:
        trong = sum(1 for t, o in o_sub if phu(t, o))
        ok("vùng mờ phủ ≥ 97% ô chữ Hán đáy khung", trong / len(o_sub) >= 0.97,
           f"{trong}/{len(o_sub)} = {trong / len(o_sub):.0%}" + ("" if vung else " · thiếu 05_hinh/vung_mo.json (chạy B5)"))
    else:
        ok("có chữ Hán đáy khung để mờ", False, f"OCR thấy 0 ô ({'chưa có 05_hinh/ocr_khung.json — chạy B5' if not ocr else 'phim không có phụ đề in'})",
           canh_bao=True)
    png = list((d / "05_hinh/sub_png").glob("cau_*.png"))
    co_loi = sum(1 for c in cau if c.get("vi"))
    ok("PNG phụ đề = số câu có lời", len(png) == co_loi, f"{len(png)} png / {co_loi} câu có lời")
    # 6. Nhạc (không bắt buộc)
    cue = doc_json(d / "06_nhac/nhac_cue.json") or {}
    if cue.get("khong_nhac"):
        ok("nhạc nền", True, "chọn không dùng nhạc (--khong-nhac)")
    else:
        cues = cue.get("cues", [])
        ok("có khoảng nhạc và mọi khoảng có bài", bool(cues) and all(c.get("file") for c in cues), f"{len(cues)} khoảng", canh_bao=True)
    # 7. Gói đăng
    bd = doc_json(d / "08_dang/bai_dang.json") or {}
    bia = bd.get("bia") or ""
    bia_p = Path(bia) if Path(bia).is_absolute() else d / bia
    ok("bai_dang.json có tiêu đề + bìa", bool(bd.get("tieu_de")) and bool(bia) and bia_p.exists(), (bd.get("tieu_de") or "chưa chốt")[:60],
       canh_bao=not a.truoc_dang)
    if bd.get("tieu_de"):
        ok("tiêu đề ≤ 70 ký tự, không chữ Hán", len(bd["tieu_de"]) <= 70 and not CJK.search(bd["tieu_de"]), f"{len(bd['tieu_de'])} ký tự")
    kk = sorted((d / "07_out/khung_kiem").glob("*.jpg"))
    ok("có ≥ 3 khung kiểm", len(kk) >= 3, f"{len(kk)} khung")

    do = [r for r in R if r[0] == "🔴"]; vang = [r for r in R if r[0] == "🟡"]
    ket = "PASS" if not do else "FAIL"
    dong = [f"# KIỂM TẬP `{a.tap}` — **{ket}** ({len(do)} 🔴 · {len(vang)} 🟡 · {len(R) - len(do) - len(vang)} OK) · {len(R)} mục · "
            f"{'TRƯỚC ĐĂNG' if a.truoc_dang else 'sau dựng (bìa chưa chốt = 🟡)'}", ""]
    dong += [f"- {m} {ten} — {ct}" for m, ten, ct in R]
    dong += ["", "Cổng máy chỉ bắt lỗi ĐÚNG/SAI đo được. Đẹp/xấu, giọng có rề, dịch có sát: mắt + tai người dùng."]
    (d / "07_out").mkdir(exist_ok=True)
    (d / "07_out/KIEM.md").write_text("\n".join(dong) + "\n", encoding="utf-8")
    (d / "07_out/KIEM.json").write_text(json.dumps({"ket": ket, "truoc_dang": a.truoc_dang, "do": [r[1] for r in do], "vang": [r[1] for r in vang],
                                                    "xin_phep": xp, "muc": [{"muc": m, "ten": ten, "chi_tiet": ct} for m, ten, ct in R]},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(dong))
    sys.exit(0 if ket == "PASS" else 1)


if __name__ == "__main__":
    main()
