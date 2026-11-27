"""B7 — DỰNG: mờ chữ Trung + phụ đề Việt + trộn tiếng (tiếng gốc · giọng Việt · nhạc nén dưới giọng) → chuẩn −14 LUFS
→ `07_out/<slug>_final.mp4` + `QC.md` + 3 khung kiểm `07_out/khung_kiem/`.

Hình: một lượt ffmpeg mỗi ≤ 100 lớp phụ đề (ảnh PNG cả khung + enable=between(t,a,b)); lượt trung gian crf 12, lượt cuối crf 18.
Dải phụ đề Trung mờ (boxblur) đúng các khoảng có chữ; ô tĩnh (logo) mờ suốt phim; ô «them» mờ đúng khoảng của nó.
Tiếng: trộn ra wav → loudnorm 2 lượt tuyến tính (không alimiter) → ghép.

    python -m ptm.b7_dung --tap <slug> [--khong-nhac] [--crf 18]
"""
import argparse, json, math, re, subprocess, sys, time
from pathlib import Path

from .chung import CAU_HINH, can, chay, doc_cau, doc_json, doc_tap, ffprobe_dur, ffprobe_video, log, tap_dir, xong_buoc

LO = 100


def bieu_thuc_enable(khoang):
    return "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in khoang) or "0"


def loc_mo(vung, W, H):
    """Chuỗi filter làm mờ: dải sub theo khoảng + ô tĩnh suốt phim + ô thêm theo khoảng. Trả (filter, nhãn ra).
    Ô kẹp trong khung W×H (ô tràn mép làm crop của ffmpeg hỏng)."""
    r = CAU_HINH["mo_ban_kinh"]
    chuoi, cur, k = [], "[0:v]", 0
    vung_ds = []
    if vung.get("dai_sub") and vung.get("khoang"):
        vung_ds.append((vung["dai_sub"], vung["khoang"]))
    for o in vung.get("tinh") or []:
        vung_ds.append((o, None))
    for o in vung.get("them") or []:
        vung_ds.append((o, o.get("khoang") or None))
    for o, kh in vung_ds:
        try:
            x1, x2 = sorted(min(W, max(0, int(float(o[k])))) for k in ("x1", "x2"))
            y1, y2 = sorted(min(H, max(0, int(float(o[k])))) for k in ("y1", "y2"))
        except (KeyError, TypeError, ValueError):
            log(f"⚠️ vung_mo.json: ô sai dạng {o} — bỏ"); continue
        w, h = x2 - x1, y2 - y1
        if w < 8 or h < 8:
            continue
        w -= w % 2; h -= h % 2
        en = f":enable='{bieu_thuc_enable(kh)}'" if kh else ""
        # boxblur: bán kính ≤ nửa cạnh nhỏ (luma) và ≤ 1/4 cạnh (chroma yuv420) ⇒ tự co theo vùng
        rl = max(1, min(r, min(w, h) // 2 - 1)); rc = max(1, min(rl, min(w, h) // 4 - 1))
        chuoi.append(f"{cur}split[s{k}][c{k}];[c{k}]crop={w}:{h}:{x1}:{y1},boxblur={rl}:2:{rc}:2[b{k}];"
                     f"[s{k}][b{k}]overlay={x1}:{y1}{en}[v{k}]")
        cur = f"[v{k}]"; k += 1
    return ";".join(chuoi), cur


def dung_hinh(goc, vung, cau, sub_dir, ra_dir, crf, W, H):
    lop = [(sub_dir / f"cau_{c['id']:03d}.png", c["start"], c["end"]) for c in cau if (sub_dir / f"cau_{c['id']:03d}.png").exists()]
    # phụ đề hiện tới ngay trước câu sau (đọc kịp), tối đa +0,8 s
    for i in range(len(lop)):
        sau = lop[i + 1][1] if i + 1 < len(lop) else lop[i][2] + 5
        lop[i] = (lop[i][0], lop[i][1], max(lop[i][1] + 0.05, min(sau - 0.05, lop[i][2] + 0.8)))   # hai câu sát nhau: cuối ≥ đầu + 0,05
    nguon, tam = goc, []
    tong_luot = max(1, (len(lop) + LO - 1) // LO)
    for luot in range(tong_luot):
        phan = lop[luot * LO:(luot + 1) * LO]
        ins = ["-i", str(nguon)]
        fc, cur = ("", "[0:v]")
        if luot == 0:
            fc, cur = loc_mo(vung, W, H)
        for j, (png, a, b) in enumerate(phan, 1):
            ins += ["-loop", "1", "-framerate", "2", "-i", str(png)]
            fc += (";" if fc else "") + f"{cur}[{j}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})':eof_action=pass[o{j}]"
            cur = f"[o{j}]"
        cuoi = luot == tong_luot - 1
        ra = ra_dir / ("hinh.mp4" if cuoi else f"_tam_{luot}.mp4")
        cmd = [can("ffmpeg"), "-hide_banner", "-v", "error", "-stats", "-y", *ins]
        cmd += ["-filter_complex", fc, "-map", cur] if fc else ["-map", "0:v"]
        cmd += ["-an", "-c:v", "libx264", "-preset", "medium" if cuoi else "fast", "-crf", str(crf if cuoi else 12),
                "-pix_fmt", "yuv420p", "-shortest", str(ra)]
        log(f"hình lượt {luot + 1}/{tong_luot}: {len(phan)} lớp sub")
        chay(cmd, im=True)
        if nguon != goc:
            tam.append(nguon)
        nguon = ra
    for t in tam:
        Path(t).unlink(missing_ok=True)
    return ra_dir / "hinh.mp4"


def tron_tieng(d, ra, tong, co_nhac):
    tg, gv, nb = d / "02_tieng/tieng_sfx.wav", d / "04_giong/giong_viet.wav", d / "06_nhac/nhac_bed.wav"
    ins = ["-i", str(tg), "-i", str(gv)]
    fc = (f"[0:a]aresample=48000,volume={CAU_HINH['tieng_goc_volume']}[t];"
          f"[1:a]aresample=48000,volume={CAU_HINH['giong_viet_volume']}[g]")
    if co_nhac and nb.exists():
        ins += ["-i", str(nb)]
        # nhạc bị nén khi giọng Việt nói (sidechain, giọng làm khoá)
        fc += (f";[2:a]aresample=48000,volume={CAU_HINH['nhac_volume']}[n0];[1:a]aresample=48000,asplit[k1][k2];"
               f"[n0][k1]sidechaincompress=threshold=0.02:ratio=5:attack=30:release=500:makeup=1[n];"
               f"[t][k2]amix=inputs=2:normalize=0:weights='1 0'[t2]")
        fc += ";[t2][g][n]amix=inputs=3:normalize=0:duration=longest[mix]"
    else:
        fc += ";[t][g]amix=inputs=2:normalize=0:duration=longest[mix]"
    fc += f";[mix]apad=whole_dur={tong:.2f},atrim=0:{tong:.2f}[a]"
    chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[a]", "-ac", "2", "-c:a", "pcm_s16le", str(ra)])


def bang_loudnorm(stderr):
    """Bảng đo loudnorm = khối {...} CUỐI có «input_i» (khối đầu có thể là chữ khác trong log)."""
    bang = [b for b in re.findall(r"\{[^{}]+\}", stderr) if '"input_i"' in b]
    return json.loads(bang[-1]) if bang else None


def so_huu_han(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def loudnorm2(wav, target):
    """2 lượt tuyến tính; TP nhắm −2,0 dBTP vì AAC nâng đỉnh ~0,5 dB. Bản trộn im lặng (đo ra −inf) ⇒ bỏ lượt 2, trả None."""
    p = subprocess.run([can("ffmpeg"), "-hide_banner", "-v", "info", "-i", str(wav), "-af",
                        f"loudnorm=I={target}:TP=-2.0:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = bang_loudnorm(p.stderr)
    if not m:
        raise RuntimeError("loudnorm không trả bảng đo: " + p.stderr[-400:])
    if not all(so_huu_han(m.get(k)) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
        log(f"🔴 bản trộn tiếng IM LẶNG hoặc đo hỏng (input_i={m.get('input_i')}, input_tp={m.get('input_tp')}) — bỏ chuẩn hoá loudness; "
            "kiểm 02_tieng/tieng_sfx.wav, 04_giong/giong_viet.wav")
        return None
    ra = str(wav) + ".ln.wav"
    chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", str(wav), "-af",
          (f"loudnorm=I={target}:TP=-2.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
           f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"),
          "-ar", "48000", "-f", "wav", ra], im=True)
    Path(ra).replace(wav)
    return float(m["input_i"])


def do_lufs(f):
    p = subprocess.run([can("ffmpeg"), "-hide_banner", "-v", "info", "-i", str(f), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    return bang_loudnorm(p.stderr) or {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b7_dung", description="B7 — dựng bản cuối")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--khong-nhac", action="store_true")
    ap.add_argument("--crf", type=int, default=18)
    a = ap.parse_args(argv)
    can("ffmpeg"); can("ffprobe")
    d = tap_dir(a.tap)
    t = doc_tap(a.tap)
    goc = d / "01_raw/goc.mp4"
    thieu = [p for p in ("01_raw/goc.mp4", "02_tieng/tieng_sfx.wav", "04_giong/giong_viet.wav") if not (d / p).exists()]
    if thieu:
        sys.exit(f"🔴 Thiếu {', '.join(thieu)} — chạy các bước trước")
    cau, _ = doc_cau(d)
    vung = doc_json(d / "05_hinh/vung_mo.json") or {}
    if not vung:
        log("⚠️ thiếu 05_hinh/vung_mo.json — không làm mờ chữ Trung")
    sub = d / "05_hinh/sub_png"
    so_png = len(list(sub.glob("cau_*.png"))) if sub.exists() else 0
    if not so_png:
        log("⚠️ không có 05_hinh/sub_png/cau_*.png — bản dựng không có phụ đề Việt (chạy B5)")
    out = d / "07_out"; out.mkdir(exist_ok=True)
    (out / "khung_kiem").mkdir(exist_ok=True)
    vi = t.get("video") or ffprobe_video(goc)
    tong = vi["dur"]
    t0 = time.time()
    hinh = dung_hinh(goc, vung, cau, sub, out, a.crf, int(vi["w"]), int(vi["h"]))
    mix = out / "mix.wav"
    co_nhac = not a.khong_nhac and not (doc_json(d / "06_nhac/nhac_cue.json") or {}).get("khong_nhac")
    tron_tieng(d, mix, tong, co_nhac)
    lufs_truoc = loudnorm2(mix, CAU_HINH["lufs"])
    final = out / f"{a.tap}_final.mp4"
    chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", str(hinh), "-i", str(mix), "-map", "0:v", "-map", "1:a",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(final)])
    # QC
    dur_f = ffprobe_dur(final)
    ln = do_lufs(final)
    for f in (out / "khung_kiem").glob("*.jpg"):
        f.unlink()
    for k, p in enumerate((0.1, 0.5, 0.9)):
        tt = tong * p
        gan = min(cau, key=lambda c: abs(c["start"] - tt)) if cau else None   # mốc có phụ đề gần nhất để nhìn được chữ
        tt = (gan["start"] + 0.5) if gan else tt
        tt = min(max(0.0, tong - 0.5), tt)   # không tua quá đuôi phim (ra khung rỗng)
        subprocess.run([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-ss", f"{tt:.2f}", "-i", str(final), "-frames:v", "1",
                        str(out / "khung_kiem" / f"k{k + 1}_{int(tt)}s.jpg")])
    qc = {"dur_goc": round(tong, 2), "dur_final": round(dur_f, 2), "lech_giay": round(dur_f - tong, 2),
          "lufs_mix_truoc_chuan": round(lufs_truoc, 1) if lufs_truoc is not None else "im_lang", "lufs_final": ln.get("input_i"), "tp_final": ln.get("input_tp"),
          "so_sub": so_png, "so_cau": len(cau), "so_khoang_mo": len(vung.get("khoang") or []), "o_tinh": len(vung.get("tinh") or []),
          "co_nhac": bool(co_nhac and (d / "06_nhac/nhac_bed.wav").exists()), "giay_dung": round(time.time() - t0)}
    dat = bool(abs(qc["lech_giay"]) <= 0.15 and lufs_truoc is not None and so_huu_han(ln.get("input_i"))
               and abs(float(ln["input_i"]) - CAU_HINH["lufs"]) <= 1.0
               and so_huu_han(ln.get("input_tp")) and float(ln["input_tp"]) <= -1.0)   # cùng cổng với kiem.py
    (out / "QC.md").write_text("# QC bản dựng\n\n" + "\n".join(f"- {k}: {v}" for k, v in qc.items()) +
                               f"\n\n**Máy chấm: {'ĐẠT' if dat else 'KHÔNG ĐẠT'}** (lệch giây ≤ 0,15 · LUFS ±1 · true peak ≤ −1 dBTP). "
                               "Mắt + tai người dùng là cổng cuối: xem `khung_kiem/` + nghe 1 phút đầu.\n", encoding="utf-8")
    log(f"xong {final.name} · {qc}")
    mix.unlink(missing_ok=True)
    hinh.unlink(missing_ok=True)   # hình trung gian đã ghép vào final
    xong_buoc(a.tap, "b7_dung", dat=dat, **qc, file=str(final.relative_to(d)))
    if not dat:
        sys.exit(1)


if __name__ == "__main__":
    main()
