# Quản lý tài khoản Buzz

[English](README.md) · [한국어](README.ko.md) · Tiếng Việt

**Chọn tài khoản đăng ký, mô hình và mức độ suy luận cho từng tác nhân Buzz trên macOS.**

[Tải bản macOS](https://github.com/ttalkkaklab/buzz-account-manager/releases/latest) · Giấy phép [MIT](LICENSE)

Ứng dụng SwiftUI hỗ trợ Codex, Claude Code, Grok và máy chủ Ollama. Giao diện có tiếng Việt, tiếng Anh và tiếng Hàn. Đây là dự án cộng đồng độc lập, không phải ứng dụng chính thức của Buzz hay các nhà cung cấp AI.

## Cài đặt

Bản tải xuống dành cho Apple Silicon, macOS 14 trở lên. Cần cài Buzz Desktop tại `/Applications/Buzz.app`, tạo tác nhân trong Buzz và cài CLI cùng bộ chuyển đổi ACP của dịch vụ:

- Codex: `codex` và `codex-acp`.
- Claude Code: `claude` và `claude-agent-acp`.
- Grok: `grok`.
- Ollama: máy chủ đang chạy, mô hình cục bộ hỗ trợ gọi công cụ và `claude-agent-acp`.

Ứng dụng dùng `/usr/bin/python3` từ Xcode Command Line Tools. Có thể cài bằng `xcode-select --install`.

1. Tải ZIP từ trang Releases và giải nén.
2. Chuyển **Buzz Account Manager.app** vào `~/Applications`.
3. Mở ứng dụng, chọn **Tài khoản đăng ký → Thêm tài khoản** rồi đăng nhập.
4. Chọn tác nhân, tài khoản, mô hình và mức suy luận, sau đó nhấn **Lưu và khởi động lại Buzz**.

Bản phát hành chỉ có chữ ký ad-hoc, chưa được Apple công chứng. Nếu macOS chặn ứng dụng, kiểm tra trong Cài đặt hệ thống → Quyền riêng tư & Bảo mật hoặc tự biên dịch từ mã nguồn. ZIP không chứa thông tin đăng nhập.

## Dung lượng và tài khoản dự phòng

Màn hình tài khoản và tác nhân hiển thị hạn mức Codex, Claude Code còn lại. Nhấn **Xem chi tiết** để xem các hạn mức bổ sung và thời gian đặt lại. Các tỷ lệ do nhà cung cấp trả về, không phải số token chính xác. Chưa hỗ trợ kiểm tra hạn mức Grok. Ollama chạy mô hình cục bộ nên không dùng hạn mức đăng ký.

Mỗi tác nhân có thể chọn tối đa ba tài khoản dự phòng cùng dịch vụ. Đăng nhập vào các tài khoản đó, bật tự động chuyển rồi lưu. Tính năng này mặc định tắt.

Tiến trình nền kiểm tra mỗi năm phút khi bạn đã đăng nhập vào macOS và máy không ngủ, kể cả khi đóng ứng dụng. Chỉ chuyển khi kết quả mới xác nhận hết hạn mức áp dụng cho mô hình hiện tại và tài khoản dự phòng còn dung lượng. Không chuyển khi kiểm tra thất bại hoặc dữ liệu đã cũ. Giữ nguyên mô hình và mức suy luận.

**Lưu cài đặt tác nhân hoặc tự động chuyển tài khoản sẽ khởi động lại Buzz, có thể ngắt phản hồi của mọi tác nhân. Yêu cầu bị ngắt không được tự động gửi lại.**

## Ngôn ngữ và dữ liệu

Chọn **Ngôn ngữ** ở cuối thanh bên để đổi ngay giữa tiếng Việt, tiếng Anh và tiếng Hàn. Lựa chọn được lưu riêng trên từng máy Mac. Tên tác nhân, tên tài khoản và ID mô hình được giữ nguyên. Nhật ký CLI và trang đăng nhập theo cài đặt của dịch vụ.

CLI lưu thông tin xác thực. Tài khoản mới dùng thư mục riêng trong `~/.config/buzz-agents/accounts/`. Cài đặt, bản sao lưu và bộ nhớ đệm hạn mức cũng nằm trong `~/.config/buzz-agents/`. Tách thư mục không tạo vùng cách ly bảo mật: các tác nhân vẫn chạy dưới cùng người dùng macOS.

Xem [README tiếng Anh](README.md) để biết cách biên dịch, kiểm thử và cấu trúc lưu trữ. Đóng góp bản dịch và báo lỗi đều được hoan nghênh. Không đăng token hoặc thông tin đăng nhập trong issue.
