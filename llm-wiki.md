# LLM Wiki — Giao Dịch Hàng Hóa

Dự án này: theo dõi và phân tích thị trường hàng hóa.

---

## Khái niệm cốt lõi

Hầu hết mọi người dùng LLM theo kiểu RAG: upload file, LLM tìm đoạn liên quan khi hỏi, trả lời. Không có gì tích lũy. Hỏi câu phức tạp cần tổng hợp 5 tài liệu thì LLM phải tìm lại từ đầu mỗi lần.

Cách tiếp cận ở đây khác: thay vì chỉ truy xuất từ tài liệu thô, LLM **xây dựng và duy trì một wiki bền vững** — tập hợp các file markdown có cấu trúc và liên kết với nhau. Khi thêm nguồn mới, LLM không chỉ index để tra sau — nó đọc, trích xuất thông tin quan trọng, tích hợp vào wiki hiện tại: cập nhật trang entity, sửa lại bản tóm tắt, ghi nhận mâu thuẫn với thông tin cũ. Kiến thức được biên soạn một lần và **liên tục cập nhật**.

**Wiki là artifact bền vững và tích lũy.** Cross-reference đã có sẵn. Mâu thuẫn đã được gắn cờ. Tổng hợp đã phản ánh mọi thứ đã đọc. Wiki ngày càng phong phú với mỗi nguồn thêm vào và mỗi câu hỏi đặt ra.

Bạn không tự viết wiki — LLM viết và duy trì tất cả. Bạn chịu trách nhiệm: chọn nguồn, định hướng phân tích, đặt câu hỏi đúng. LLM lo phần còn lại: tóm tắt, cross-reference, phân loại, bookkeeping.

---

## Kiến trúc 3 lớp

**Nguồn thô (raw/)** — bộ sưu tập tài liệu nguồn. File Excel, PDF, ảnh, dữ liệu. Bất biến — LLM chỉ đọc, không sửa. Đây là source of truth.

**Wiki (wiki/)** — thư mục các file markdown do LLM tạo ra. Tóm tắt, trang entity, trang concept, so sánh, tổng hợp. LLM sở hữu lớp này hoàn toàn — tạo trang, cập nhật khi có nguồn mới, duy trì cross-reference. Bạn đọc; LLM viết.

**Schema (CLAUDE.md)** — tài liệu hướng dẫn LLM: cấu trúc wiki, quy ước, workflow khi thêm nguồn, trả lời câu hỏi, duy trì wiki. Đây là file cấu hình chủ chốt — biến LLM từ chatbot generic thành người quản lý wiki có kỷ luật.

---

## Các thao tác chính

**Ingest (thêm nguồn mới).** Bạn đưa nguồn mới vào `raw/` và báo LLM xử lý. Ví dụ flow: LLM đọc nguồn → thảo luận điểm chính với bạn → viết trang tóm tắt vào wiki → cập nhật index → cập nhật các trang entity và concept liên quan. Một nguồn có thể chạm đến 10-15 trang wiki. Có thể ingest từng nguồn một (có sự tham gia của bạn) hoặc batch nhiều nguồn cùng lúc (ít giám sát hơn).

**Query (đặt câu hỏi).** Bạn hỏi, LLM tìm trang wiki liên quan, đọc, tổng hợp câu trả lời có trích dẫn. Câu trả lời hay nên được lưu lại thành trang wiki mới — phân tích, so sánh, kết nối bạn khám phá ra đều có giá trị và không nên mất đi trong lịch sử chat. Cách này giúp các khám phá của bạn tích lũy vào knowledge base.

**Lint (kiểm tra sức khỏe wiki).** Định kỳ yêu cầu LLM kiểm tra: mâu thuẫn giữa các trang, thông tin cũ bị nguồn mới hơn vượt qua, trang mồ côi không có inbound link, concept quan trọng được nhắc đến nhưng chưa có trang riêng, gap dữ liệu có thể bổ sung bằng web search.

---

## Index và Log

**wiki/index.md** — theo nội dung. Catalog mọi thứ trong wiki: mỗi trang có link, tóm tắt 1 dòng, metadata (ngày, số nguồn). Tổ chức theo category. LLM cập nhật sau mỗi lần ingest. Khi trả lời query, LLM đọc index trước để tìm trang liên quan.

**wiki/log.md** — theo thời gian. Nhật ký append-only ghi lại những gì đã xảy ra và khi nào — ingest, query, lint pass. Mỗi entry bắt đầu bằng prefix nhất quán, ví dụ `## [2026-06-05] ingest | Tên tài liệu`. Log cho thấy timeline tiến hóa của wiki và giúp LLM hiểu những gì đã làm gần đây.

---

## Tại sao cách này hiệu quả

Phần tẻ nhạt của việc duy trì knowledge base không phải đọc hay suy nghĩ — mà là bookkeeping. Cập nhật cross-reference, giữ tóm tắt hiện tại, ghi nhận khi dữ liệu mới mâu thuẫn với cũ, duy trì nhất quán qua hàng chục trang. Con người bỏ cuộc với wiki vì chi phí bảo trì tăng nhanh hơn giá trị. LLM không chán, không quên cập nhật cross-reference, có thể chạm vào 15 file trong một lần. Wiki được duy trì vì chi phí bảo trì gần như bằng không.

Nhiệm vụ của bạn: chọn nguồn, định hướng phân tích, đặt câu hỏi tốt, suy nghĩ về ý nghĩa. Nhiệm vụ của LLM: mọi thứ còn lại.

---

## Ghi chú áp dụng cho dự án này

- **`raw/`** — dữ liệu gốc bất biến (Excel, PDF, JSON thô...)
- **`wiki/`** — LLM tạo và duy trì: tóm tắt, phân tích, cross-reference
- **`wiki/index.md`** — catalog tự động cập nhật sau mỗi lần thêm nội dung
- **`wiki/log.md`** — nhật ký append-only theo format `## [YYYY-MM-DD] <thao tác> | <chi tiết>`
- **`CLAUDE.md`** — schema/rubric hướng dẫn agent vận hành dự án này

> Khi thêm tài liệu/dữ liệu mới: đặt vào `raw/` → nói với Claude "ingest [tên file]" → Claude cập nhật wiki.