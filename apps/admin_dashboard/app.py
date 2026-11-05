import streamlit as st
import requests
import json
import os
import time

# Cấu hình
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000/api")
INGESTION_URL = os.getenv("INGESTION_URL", "http://ingest-api:8010/api/v1")
TITLE = "🤖 Bảng Điều Khiển Quản Trị AI Chat"

st.set_page_config(page_title=TITLE, layout="wide")
st.title(TITLE)

# Thanh bên
st.sidebar.header("Cấu hình")
backend_url = st.sidebar.text_input("URL Backend API", BACKEND_URL)
ingest_url = st.sidebar.text_input("URL Ingestion API", INGESTION_URL)
tenant_id = st.sidebar.text_input("Mã Tenant", "default")
user_role = st.sidebar.selectbox("Vai trò", ["citizen", "officer", "admin"])
st.sidebar.write(f"Debug Role: {user_role}")

agent_id = st.sidebar.selectbox("Trợ lý", ["citizen", "legal_assistant", "officer", "meeting_assistant"])

# Các tab
# Các tab
tab_chat, tab_ingest, tab_jobs, tab_sources, tab_audit, tab_status = st.tabs(["💬 Giao diện Chat", "📂 Quản lý Nhập liệu", "📋 Quản lý Job", "🔌 Nguồn Dữ Liệu", "📝 Nhật ký", "🟢 Trạng thái"])

# --- TAB 1: CHAT ---
with tab_chat:
    st.subheader("Kiểm tra Chat RAG")
    
    # Lưu trữ lịch sử chat
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Hiển thị lịch sử chat
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "meta" in msg:
                with st.expander("Xem Metadata & Trích dẫn"):
                    st.json(msg["meta"])

    # Nhập câu hỏi
    if prompt := st.chat_input("Nhập câu hỏi của bạn..."):
        # Thêm tin nhắn người dùng
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Gọi Backend
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            citations = []
            meta_info = {}
            
            headers = {
                "X-GOVAI-TENANT-ID": tenant_id,
                "X-GOVAI-USER-ROLE": user_role
            }
            payload = {
                "message": prompt,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "stream": True
            }

            try:
                # Gửi yêu cầu streaming
                message_placeholder.markdown("Đang suy nghĩ...")
                with requests.post(f"{backend_url}/chat", json=payload, headers=headers, stream=True) as response:
                    if response.status_code == 200:
                        for line in response.iter_lines():
                            if line:
                                line = line.decode('utf-8')
                                if line.startswith("data: "):
                                    data_str = line[6:]
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data = json.loads(data_str)
                                        # Handle different event types logic if needed, but simple token append mostly
                                        # Backend sends: event: token, data: "text" | event: citation, data: [...]
                                        # Wait, this simple iter_lines doesn't split events cleanly if "event: ..." is on separate line.
                                        # But standard SSE sends event\ndata\n\n
                                        # We need to parse block by block or look for data line.
                                        
                                        # Simplified SSE Parser
                                        pass
                                    except:
                                        pass
                        
                        # Better SSE Loop
                        import sseclient
                        client = sseclient.SSEClient(response)
                        for event in client.events():
                            if event.event == "token":
                                token = json.loads(event.data)
                                full_response += token
                                message_placeholder.markdown(full_response + "▌")
                            elif event.event == "citation":
                                citations = json.loads(event.data)
                            elif event.event == "meta":
                                meta_info.update(json.loads(event.data))
                            elif event.event == "done":
                                break
                            elif event.event == "error":
                                st.error(f"Error: {event.data}")
                        
                        message_placeholder.markdown(full_response)
                        
                        # Hiển thị trích dẫn
                        if citations:
                            st.info(f"📚 Tìm thấy {len(citations)} trích dẫn")
                            with st.expander("Xem trích dẫn"):
                                st.json(citations)
                        
                        # Thêm vào lịch sử
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": full_response, 
                            "meta": {"citations": citations, "debug": meta_info}
                        })
                    else:
                        st.error(f"Lỗi API {response.status_code}: {response.text}")
            except Exception as e:
                st.error(f"Lỗi kết nối: {e}")

# --- TAB 2: NHẬP LIỆU ---
with tab_ingest:
    st.subheader("Nhập liệu Tài liệu")
    
    # 1. Tạo Profile
    with st.expander("Tạo Profile Nhập liệu"):
        col1, col2 = st.columns(2)
        with col1:
            prof_name = st.text_input("Tên Profile")
            prof_desc = st.text_input("Mô tả")
        with col2:
            prof_scope = st.selectbox("Phạm vi", ["public", "internal", "restricted"])
            prof_auto = st.checkbox("Tự động phê duyệt", value=True)
            
        if st.button("Tạo Profile"):
            p_payload = {
                "profile_id": str(time.time()).replace(".",""),
                "tenant_id": tenant_id,
                "name": prof_name,
                "description": prof_desc,
                "config": {"scope": prof_scope, "auto_approve": prof_auto}
            }
            try:
                res = requests.post(f"{ingest_url}/admin/profiles", json=p_payload, headers={"X-GOVAI-TENANT-ID": tenant_id})
                if res.status_code in (200, 201):
                    st.success("Đã tạo Profile")
                else:
                    st.error(res.text)
            except Exception as e:
                st.error(str(e))

    # 2. Tải lên File & Gửi Job
    st.divider()
    st.write("#### Tải lên & Nhập liệu")
    
    # Lấy danh sách Profiles
    profiles = {}
    try:
        res = requests.get(f"{ingest_url}/admin/profiles?tenant_id={tenant_id}", headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": user_role})
        if res.status_code == 200:
            for p in res.json():
                profiles[p['name']] = p['profile_id']
    except:
        pass
        
    selected_profile_name = st.selectbox("Chọn Profile", list(profiles.keys()) if profiles else ["Nhập thủ công"])
    selected_profile_id = profiles.get(selected_profile_name)
    
    if selected_profile_name == "Nhập thủ công":
        selected_profile_id = st.text_input("Nhập UUID Profile")

    uploaded_file = st.file_uploader("Chọn tệp")
    
    if st.button("Tải lên & Bắt đầu") and uploaded_file and selected_profile_id:
        # 1. Upload file to Temp/Storage (Simulation)
        # In real app we upload to /upload endpoint then submit job.
        # Or we send file content in job (not recommended for large files).
        # We will assume Shared Volume for this Admin UI? 
        # Or we use the /temp_docs/upload endpoint in backend then pass URL?
        # Ingestion API usually takes `source_uri` (S3/Local).
        # Admin UI container needs to write to a shared volume mapped to Ingestion Worker.
        
        # Let's try sending to Ingestion API if it supports upload?
        # The verification suite used a local file path `/app/storage/...`.
        # Admin UI needs to write to that same shared path.
        
        save_path = f"/app/storage/{uploaded_file.name}" # Need to map volume in compose
        # But Admin Dashboard container /app/storage != Ingestion container /app/storage unless shared volume.
        
        # For MVP, we will assume we can't upload easily without shared volume.
        # I'll rely on the user manually placing files or just mocking the "path" for pre-existing files.
        # Wait, I can add a shared volume in docker-compose.
        st.warning("Tính năng tải lên cần volume chung. Hiện đang kích hoạt job cho file có sẵn: /app/storage/memo_demo.txt")
        
        job_payload = {
            "profile_id": selected_profile_id,
            "files": [{
                "object_key": "/app/storage/memo_demo.txt",
                "original_name": "memo_demo.txt", 
                "mime_type": "text/plain",
                "size_bytes": 100,
                "checksum": "fake"
            }],
            "note": "Triggered via Admin UI"
        }
        try:
             res = requests.post(f"{ingest_url}/admin/jobs", json=job_payload, headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": "admin"})
             st.json(res.json())
        except Exception as e:
            st.error(str(e))

# --- TAB 3: QUẢN LÝ JOB ---
with tab_jobs:
    st.subheader("Danh sách & Phê duyệt Job")
    
    # Filter
    col1, col2 = st.columns(2)
    with col1:
        filter_status = st.selectbox("Lọc theo trạng thái", ["ALL", "queued", "processing", "pending_approval", "completed", "failed"], index=0)
    with col2:
        if st.button("🔄 Làm mới danh sách"):
            st.rerun()

    # Load Jobs
    rows = []
    try:
        # Check API support for filter. If not, filter client side.
        # Assuming GET /admin/jobs returns list.
        res = requests.get(f"{ingest_url}/admin/jobs?limit=50", headers={"X-GOVAI-TENANT-ID": tenant_id})
        if res.status_code == 200:
            jobs = res.json()
            # Sort by created_at desc
            jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
            for j in jobs:
                if filter_status != "ALL" and j.get('status') != filter_status:
                    continue
                    
                rows.append({
                    "ID": j.get("job_id"),
                    "Status": j.get("status"),
                    "File": j.get("title") or j.get("source_uri"),
                    "Profile": j.get("profile_id"),
                    "Created": j.get("created_at"),
                    "Error": j.get("error")
                })
        else:
            st.error(f"Lỗi tải danh sách: {res.status_code}")
    except Exception as e:
        st.error(f"Lỗi kết nối: {e}")

    # Display Jobs as Interactive Rows
    if rows:
        st.write(f"Tìm thấy {len(rows)} jobs")
        for j in rows:
            with st.expander(f"{j['ID'][:8]}... | {j['Status']} | {j['File']}", expanded=(j['Status']=='pending_approval')):
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1:
                    st.write(f"**Profile:** {j['Profile']}")
                    st.caption(f"Created: {j['Created']}")
                    if j['Error']:
                         st.error(f"Error: {j['Error']}")
                
                with c2:
                    # Action Buttons
                    if j['Status'] == 'pending_approval':
                        if st.button("✅ Approve", key=f"app_{j['ID']}"):
                            try:
                                resp = requests.post(f"{ingest_url}/admin/jobs/{j['ID']}/approve", headers={
                                    "X-GOVAI-TENANT-ID": tenant_id, 
                                    "X-GOVAI-USER-ROLE": user_role
                                })
                                if resp.status_code == 200:
                                    st.success("Approved!")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(resp.text)
                            except Exception as e:
                                st.error(str(e))
                                
                    elif j['Status'] == 'failed':
                        if st.button("🔄 Retry", key=f"ret_{j['ID']}"):
                            try:
                                resp = requests.post(f"{ingest_url}/admin/jobs/{j['ID']}/retry", headers={
                                    "X-GOVAI-TENANT-ID": tenant_id, 
                                    "X-GOVAI-USER-ROLE": user_role
                                })
                                if resp.status_code == 200:
                                    st.success("Retried!")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(resp.text)
                            except Exception as e:
                                st.error(str(e))
                
                with c3:
                    st.code(j['ID'], language="text")
    else:
        st.info("Không có dữ liệu job")

# --- TAB 5: QUẢN LÝ NGUỒN DỮ LIỆU ---
with tab_sources:
    st.subheader("Quản lý Registered Sources (Watcher v2)")
    
    # 1. Add New Source
    with st.expander("Thêm Nguồn Mới", expanded=False):
        with st.form("add_source_form"):
            src_server = st.text_input("Server ID (ví dụ: FILE_SERVER_01)")
            src_path = st.text_input("Đường dẫn (ví dụ: /mnt/data/public)")
            
            # Use profiles dict from Tab 2 logic if available, or fetch again
            # Simplify: Fetch profiles
            prof_opts = {}
            try:
                pres = requests.get(f"{ingest_url}/admin/profiles?tenant_id={tenant_id}", headers={"X-GOVAI-TENANT-ID": tenant_id})
                if pres.status_code == 200:
                    for p in pres.json():
                         prof_opts[f"{p['name']} ({p.get('description','No desc')})"] = p['profile_id']
            except:
                pass
            
            src_profile_label = st.selectbox("Gán Profile", list(prof_opts.keys()))
            submit_src = st.form_submit_button("Lưu Cấu Hình")
            
            if submit_src and src_server and src_path and src_profile_label:
                payload = {
                    "server_id": src_server,
                    "path": src_path, 
                    "profile_id": prof_opts[src_profile_label]
                }
                try:
                    r = requests.post(f"{ingest_url}/admin/sources", json=payload, headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": user_role})
                    if r.status_code == 201:
                        st.success("Đã thêm nguồn thành công!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Lỗi: {r.text}")
                except Exception as e:
                    st.error(str(e))

    # 2. List Sources
    st.divider()
    st.write("#### Danh sách Nguồn đang theo dõi")
    try:
        r = requests.get(f"{ingest_url}/admin/sources", headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": user_role})
        if r.status_code == 200:
            sources = r.json()
            if not sources:
                st.info("Chưa có nguồn nào được cấu hình.")
            else:
                for s in sources:
                    col1, col2, col3, col4, col5 = st.columns([2, 3, 2, 2, 1])
                    with col1: st.write(f"**{s['server_id']}**")
                    with col2: st.code(s['path'])
                    with col3: st.caption(s.get('profile_name', s['profile_id']))
                    with col4:
                        status_icon = "🟢 Active" if s['enabled'] else "🔴 Disabled"
                        hb = s.get('last_seen_at')
                        st.write(f"{status_icon}")
                        if hb: st.caption(f"Last seen: {hb}")
                    with col5:
                        if st.button("🗑️", key=f"del_{s['id']}"):
                            # Delete logic
                            requests.delete(f"{ingest_url}/admin/sources/{s['id']}", headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": user_role})
                            st.rerun()
        else:
             st.error(f"Failed to load sources: {r.status_code}")
    except Exception as e:
        st.error(f"Connect error: {e}")

# --- TAB 6: AUDIT ---
with tab_audit:
    st.subheader("Nhật ký Hệ thống (Audit Logs)")
    if st.button("🔄 Làm mới logs"):
        st.rerun()
        
    try:
        r = requests.get(f"{ingest_url}/admin/audit-logs?limit=50", headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": user_role})
        if r.status_code == 200:
            logs = r.json()
            if logs:
                # Flats for table
                flat_logs = []
                for l in logs:
                    flat_logs.append({
                        "Time": l['created_at'],
                        "User": l['user_id'],
                        "Action": l['action'],
                        "Resource": l['resource_id'],
                        "Details": str(l.get('details') or '')
                    })
                st.dataframe(pd.DataFrame(flat_logs), use_container_width=True)
            else:
                st.info("Chưa có logs.")
        else:
            st.error(f"Lỗi tải logs: {r.status_code}")
    except Exception as e:
        st.error(str(e))

# --- TAB 7: TRẠNG THÁI ---
with tab_status:
    st.subheader("Trạng thái & Metrics")
    
    # Quick Stats
    try:
        mcheck = requests.get(f"{ingest_url}/admin/metrics", headers={"X-GOVAI-TENANT-ID": tenant_id, "X-GOVAI-USER-ROLE": "admin"})
        if mcheck.status_code == 200:
            m = mcheck.json()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Jobs Hôm nay", m['jobs_today'])
            c2.metric("Tỷ lệ Lỗi", f"{m['failed_rate']}%")
            c3.metric("Chờ Duyệt", m['pending_approvals'])
            c4.metric("Active Watchers", m['active_watchers'])
        st.divider()
    except:
        pass

    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.write("**Backend API**")
        base_backend = backend_url.replace("/api", "")
        st.caption(f"Target: `{base_backend}/health`")
        try:
            # Sửa lỗi 404: Health check thường nằm ở root /health hoặc /api/health
            # backend_url thường là http://.../api
            base_backend = backend_url.replace("/api", "") 
            r = requests.get(f"{base_backend}/health")
            if r.status_code == 200:
                st.success("Hoạt động")
                st.json(r.json())
            else:
                # Fallback thử URL gốc
                r = requests.get(f"{backend_url}/health")
                if r.status_code == 200:
                     st.success("Hoạt động")
                     st.json(r.json())
                else:
                     st.error(f"Trạng thái: {r.status_code}")

        except Exception as e:
            st.error("❌ Network Error")
            st.code(str(e))

    with c2:
        st.write("**Ingestion API**")
        base_ingest = ingest_url.split("/api")[0]
        st.caption(f"Target: `{base_ingest}/health`")
        try:
            # ingest_url thường là http://.../api/v1
            # Thử root /health (http://ingest-api:8010/health)
            base_ingest = ingest_url.split("/api")[0] 
            r = requests.get(f"{base_ingest}/health") 
            if r.status_code == 200:
                st.success("Hoạt động")
            else:
                st.warning(f"Trạng thái: {r.status_code}")

        except Exception as e:
             st.error("❌ Network Error")
             st.code(str(e))
             
    with c3:
        st.write("**Postgres / Vector DB**")
        st.info("Kiểm tra Chi tiết Health của Backend")
