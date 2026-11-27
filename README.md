# phim-thuyet-minh — làm video thuyết minh tiếng Việt từ phim hoạt hình Trung Quốc

Bộ mã chạy trên máy bạn (macOS hoặc Linux) để biến một video Douyin / Bilibili thành video tiếng Việt: tách tiếng, nghe chữ Trung, làm mờ phụ đề
Trung, ghép giọng thuyết minh, thêm nhạc nền, dựng ra mp4 có phụ đề vàng và ảnh bìa. Không cần khoá API nào.

Bộ mã này được viết để **trợ lý AI của bạn chạy** (Claude, Codex…) cùng gói kỹ năng **HG Trend** — kỹ năng «lam-video-thuyet-minh» dặn trợ lý
làm từng bước. Những việc cần dịch vụ ngoài trợ lý làm qua HG Trend (trả bằng token của tài khoản HG):

| Việc | Ai làm |
|---|---|
| Tìm phim đang lên, đo người Việt có xem thể loại đó không | trợ lý + HG Trend |
| Lấy link tải video Douyin, Bilibili | HG Trend |
| Dò xem đã có kênh Việt làm chưa · soạn thư xin phép tác giả | máy bạn (bộ mã này) |
| Tách tiếng, nghe chữ Trung, làm mờ chữ Trung, dựng phim | máy bạn |
| Dịch lời, viết tiêu đề, chọn bìa | trợ lý |
| Đọc lời bằng giọng CapCut · nhạc nền không lời | HG Trend (hoặc nhạc riêng của bạn) |

## Cài (một lần)

```bash
git clone https://github.com/hgtrend/phim-thuyet-minh && cd phim-thuyet-minh
python3 -m pip install -r requirements.txt
```

Cần Python 3.10 trở lên và `ffmpeg` (macOS: `brew install ffmpeg` · Ubuntu: `sudo apt install ffmpeg`). Máy Mac Apple Silicon có thể cài thêm
`mlx-whisper` để nghe chữ nhanh hơn. Không có card đồ hoạ thì bước tách tiếng chạy chậm (khoảng 2–3 lần độ dài video).

## Chạy

Mỗi tập là một thư mục trong `./tap/` (đổi bằng biến `PTM_GOC`). Các bước theo thứ tự:

```bash
python3 -m ptm do-trung   --tap T01_ten_bo --ket-qua lay_link.json --bien-the "Tên Hán-Việt|Tên dịch nghĩa"
python3 -m ptm nhan       --tap T01_ten_bo --ket-qua lay_link.json      # hoặc --tep video.mp4
python3 -m ptm xin-phep   --tap T01_ten_bo --kenh "Kênh của bạn" --ten-ban "Tên bạn"
python3 -m ptm tach-tieng --tap T01_ten_bo
python3 -m ptm nghe       --tap T01_ten_bo      # phiếu dịch
python3 -m ptm giong      --tap T01_ten_bo      # phiếu đọc giọng
python3 -m ptm mo-chu     --tap T01_ten_bo
python3 -m ptm nhac       --tap T01_ten_bo      # phiếu nhạc (hoặc --khong-nhac)
python3 -m ptm dung       --tap T01_ten_bo
python3 -m ptm bia        --tap T01_ten_bo      # phiếu tiêu đề + bìa
python3 -m ptm kiem       --tap T01_ten_bo
python3 -m ptm trang-thai --tap T01_ten_bo      # tập đang ở bước nào, còn phiếu nào chờ
```

**Phiếu:** bước nào cần trợ lý (dịch, đọc giọng, nhạc, tiêu đề) thì ghi một tệp `CAN_*.json` trong thư mục tập và dừng với mã thoát 3. Trợ lý
làm đúng việc ghi trong phiếu rồi chạy lại đúng bước đó. Thêm `--help` sau mỗi bước để xem tham số.

Ra: `07_out/<tập>_final.mp4`, `07_out/KIEM.md` (bảng kiểm), `08_dang/bia_final.png` (video dọc thêm `08_dang/bia_doc.png` cho Shorts), `08_dang/bai_dang.json` (tiêu đề, mô tả, thẻ). Đăng lên
YouTube là việc của bạn.

Đổi bộ số (âm lượng, tốc độ giọng, màu phụ đề…): tạo `tap/cau_hinh.json` ghi đè các khoá trong `ptm/chung.py` (`CAU_HINH_GOC`).

## Bản quyền — đọc trước khi đăng

Phim trên Douyin, Bilibili có tác giả. Dịch, lồng tiếng rồi đăng lại mà **chưa được tác giả đồng ý** là rủi ro của bạn: kênh có thể bị báo vi phạm
bản quyền hoặc mất kiếm tiền. Bước `xin-phep` soạn sẵn thư tiếng Trung và ghi lại trạng thái; máy **chỉ nhắc, không chặn**. Nhạc nền làm bằng AI
cũng nên nghe lại trước khi đăng.

## Giấy phép

Mã: MIT (`LICENSE`). Phông chữ Baloo 2 trong `phong/`: SIL Open Font License 1.1 (`phong/OFL.txt`).

Bộ mã chuyển từ dây chuyền kênh của HG Studio. Câu hỏi, góp ý: hotro@hgstudio.work.
