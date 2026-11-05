from typing import Dict, List, Optional
from pydantic import BaseModel

class ColumnDef(BaseModel):
    name: str
    type: str
    description: Optional[str] = None

class TableDef(BaseModel):
    name: str
    columns: List[ColumnDef]
    description: Optional[str] = None

# Define Virtual Schemas (Allowlist)
# These are the ONLY tables exposed to the Text-to-SQL generator
PEOPLE_SCHEMA = TableDef(
    name="view_people",
    description="Thông tin nhân sự, cán bộ",
    columns=[
        ColumnDef(name="full_name", type="TEXT", description="Họ và tên"),
        ColumnDef(name="code", type="TEXT", description="Mã cán bộ (A, B, C...)"),
        ColumnDef(name="dob", type="TEXT", description="Ngày sinh"),
        ColumnDef(name="gender", type="TEXT", description="Giới tính"),
        ColumnDef(name="phone", type="TEXT", description="Số điện thoại"),
        ColumnDef(name="email", type="TEXT", description="Email"),
        ColumnDef(name="address", type="TEXT", description="Địa chỉ"),
        ColumnDef(name="ward_commune", type="TEXT", description="Đơn vị (Xã/Phường)"),
        ColumnDef(name="occupation", type="TEXT", description="Chức danh / Nghề nghiệp"),
        ColumnDef(name="commune_id", type="TEXT", description="ID định danh xã (bắt buộc filter)"),
    ]
)

BUDGET_SCHEMA = TableDef(
    name="view_budget",
    description="Thông tin ngân sách, tài chính",
    columns=[
        ColumnDef(name="item", type="TEXT", description="Hạng mục chi"),
        ColumnDef(name="amount", type="NUMERIC", description="Số tiền"),
        ColumnDef(name="year", type="INTEGER", description="Năm tài chính"),
        ColumnDef(name="commune_id", type="TEXT", description="ID định danh xã"),
    ]
)

# Registry of allowed schemas
ALLOWED_SCHEMAS: Dict[str, TableDef] = {
    "view_people": PEOPLE_SCHEMA,
    "view_budget": BUDGET_SCHEMA,
}
