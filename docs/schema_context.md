# Schema Context for AI Text-to-SQL

## 1. Schema Definition

### `view_people`
Thông tin về nhân sự, cán bộ, công dân.

| Column Name | Data Type | Description |
| :--- | :--- | :--- |
| `row_id` | UUID | ID duy nhất của dòng dữ liệu |
| `commune_id` | VARCHAR | Mã xã/phường (Tenant ID) |
| `full_name` | VARCHAR | Họ và tên đầy đủ |
| `code` | VARCHAR | Mã định danh, mã nhân viên |
| `dob` | VARCHAR | Ngày sinh (DD/MM/YYYY hoặc YYYY-MM-DD) |
| `gender` | VARCHAR | Giới tính (Nam/Nữ) |
| `phone` | VARCHAR | Số điện thoại |
| `email` | VARCHAR | Địa chỉ Email |
| `address` | VARCHAR | Địa chỉ thường trú/liên hệ |
| `ward_commune` | VARCHAR | Tên đơn vị hành chính (Xã/Phường) |
| `occupation` | VARCHAR | Nghề nghiệp, chức vụ |

### `view_budget`
Thông tin về ngân sách, thu chi.

| Column Name | Data Type | Description |
| :--- | :--- | :--- |
| `row_id` | UUID | ID duy nhất của dòng dữ liệu |
| `commune_id` | VARCHAR | Mã xã/phường (Tenant ID) |
| `item` | VARCHAR | Hạng mục thu/chi |
| `amount` | NUMERIC | Số tiền (VNĐ) |
| `year` | INTEGER | Năm tài chính |

## 2. Domain Dictionary (Từ điển nghiệp vụ)

### Mapping
- **Họ tên, Tên, Người, Cán bộ, Nhân sự** -> `full_name`
- **Mã, Số thẻ, ID** -> `code`
- **Ngày sinh, Sinh nhật** -> `dob`
- **Giới tính, Phái** -> `gender`
- **SĐT, Điện thoại, Di động, Phone** -> `phone`
- **Thư, Mail, Email** -> `email`
- **Địa chỉ, Nơi ở, Nhà** -> `address`
- **Xã, Phường, Đơn vị** -> `ward_commune`
- **Nghề, Công việc, Chức vụ** -> `occupation`
- **Khoản mục, Nội dung chi** -> `item`
- **Số tiền, Giá trị, Kinh phí** -> `amount`
- **Năm** -> `year`

## 3. Sample Queries

### Query 1
**Question:** "Tìm thông tin của ông Nguyễn Văn A"
**SQL:**
```sql
SELECT * FROM view_people WHERE full_name ILIKE '%Nguyễn Văn A%';
```

### Query 2
**Question:** "Liệt kê danh sách cán bộ làm nghề Giáo viên"
**SQL:**
```sql
SELECT full_name, phone, email FROM view_people WHERE occupation ILIKE '%Giáo viên%';
```

### Query 3
**Question:** "Ai là người có số điện thoại 0912345678?"
**SQL:**
```sql
SELECT * FROM view_people WHERE phone = '0912345678';
```

### Query 4
**Question:** "Tổng chi ngân sách cho hạng mục 'Xây dựng' năm 2024 là bao nhiêu?"
**SQL:**
```sql
SELECT SUM(amount) FROM view_budget WHERE item ILIKE '%Xây dựng%' AND year = 2024;
```

### Query 5
**Question:** "Danh sách các khoản chi trên 100 triệu trong năm 2025"
**SQL:**
```sql
SELECT item, amount FROM view_budget WHERE amount > 100000000 AND year = 2025;
```
