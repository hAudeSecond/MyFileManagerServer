from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash
import boto3
import io
from flask_session import Session
from botocore.exceptions import ClientError

app = Flask(__name__)

app.secret_key = 'your_secret_key'  # Bạn nên sử dụng một secret key mạnh hơn trong thực tế

# Kết nối với Amazon S3
s3 = None

@app.route('/login', methods=['GET', 'POST'])
def login():
    global s3
    if request.method == 'POST':
        access_key = request.form.get('access_key')
        secret_key = request.form.get('secret_key')
        
        if not access_key or not secret_key:
            return render_template('login.html', error="Vui lòng điền đầy đủ thông tin.")

        # Kết nối với S3 với thông tin đăng nhập
        try:
            s3 = boto3.client('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key)
            # Kiểm tra quyền truy cập bằng cách lấy danh sách các bucket
            s3.list_buckets()
            session['access_key'] = access_key  # Lưu trữ thông tin phiên người dùng
            return redirect(url_for('index'))
        except ClientError as e:
            # Bắt lỗi ClientError để tránh tiết lộ chi tiết lỗi cho người dùng
            print(f"Error connecting to S3: {e}")
            return render_template('login.html', error="Đăng nhập không thành công. Vui lòng kiểm tra thông tin.")
        except Exception as e:
            # Bắt các lỗi không phải ClientError khác
            print(f"Unexpected error: {e}")
            return render_template('login.html', error="Đã xảy ra lỗi. Vui lòng thử lại.")

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    # Xóa thông tin phiên
    session.pop('access_key', None)  # Xóa access_key
    session.pop('secret_key', None)  # Nếu bạn đã lưu secret_key trong session
    return redirect(url_for('login'))  # Chuyển hướng về trang đăng nhập



@app.route('/')
def index():
    if 'access_key' not in session:
        return redirect(url_for('login'))

    try:
        # Lấy danh sách tất cả các bucket mà người dùng có thể truy cập
        buckets = s3.list_buckets().get('Buckets', [])
        
        # Danh sách các bucket mà người dùng có quyền truy cập đầy đủ (thêm, sửa, xóa)
        accessible_buckets = []
        for bucket in buckets:
            bucket_name = bucket['Name']
            try:
                # Kiểm tra quyền thêm, sửa, xóa vào các bucket
                test_key = f"test-file-{bucket_name}.txt"
                
                # Tạo một object giả để kiểm tra quyền "PutObject"
                s3.put_object(Bucket=bucket_name, Key=test_key, Body='test')
                
                # Xóa object giả để kiểm tra quyền "DeleteObject"
                s3.delete_object(Bucket=bucket_name, Key=test_key)
                
                # Nếu không có ngoại lệ, thêm bucket vào danh sách accessible_buckets
                accessible_buckets.append(bucket)
                
            except ClientError as e:
                # Nếu gặp lỗi, người dùng không có quyền tương tác với bucket này
                print(f"User does not have full access to bucket {bucket_name}: {e}")

        return render_template('index.html', buckets=accessible_buckets)
    except Exception as e:
        print(f"Error listing buckets: {e}")
        return redirect(url_for('login'))  # Nếu có lỗi, quay lại trang đăng nhập
    
# Trang hiển thị các đối tượng trong bucket và xử lý upload/tạo thư mục
@app.route('/objects/<bucket_name>', methods=['GET', 'POST'])
def objects(bucket_name):
    message = None  # Biến để lưu thông báo

    if request.method == 'POST':
        # Xử lý upload file
        file = request.files.get('file')
        if file and file.filename:  # Kiểm tra xem file có được chọn không
            s3.upload_fileobj(file, bucket_name, file.filename)
            return redirect(url_for('objects', bucket_name=bucket_name))

        # Xử lý tạo thư mục
        try:
            folder_name = request.form.get('folder').strip()
            if folder_name:
                if not folder_name.endswith('/'):
                    folder_name += '/'
                s3.put_object(Bucket=bucket_name, Key=folder_name)
                return redirect(url_for('objects', bucket_name=bucket_name))
        except:
            return redirect(url_for('objects', bucket_name=bucket_name))

    # Lấy danh sách các đối tượng và kích thước của chúng
    objects = s3.list_objects_v2(Bucket=bucket_name).get('Contents', [])
    top_level_objects = [
        {
            'Key': obj['Key'],
            'Size': obj['Size'],
            'LastModified': obj['LastModified'],  # Thêm thông tin thời gian upload
        }
        for obj in objects if '/' not in obj['Key'].strip('/')
    ]

    return render_template('objects.html', bucket_name=bucket_name, objects=top_level_objects, message=message)



@app.route('/folder/<bucket_name>/<path:folder_name>', methods=['GET', 'POST'])
def folder(bucket_name, folder_name):
    message = None  # Biến để lưu thông báo
    
    # Lấy danh sách các đối tượng trong thư mục
    prefix = folder_name if folder_name.endswith('/') else folder_name + '/'
    objects = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix).get('Contents', [])

    # Chỉ hiển thị các đối tượng trong thư mục này (không bao gồm các đối tượng trong thư mục con)
    child_objects = [
        {
            'Key': obj['Key'],
            'Size': obj['Size'],
            'LastModified': obj['LastModified'],  # Thêm thông tin thời gian upload
        }
        for obj in objects 
        if obj['Key'] != prefix and '/' not in obj['Key'][len(prefix):].strip('/')
    ]

    # Xử lý upload file vào thư mục
    if request.method == 'POST':
        file = request.files.get('file')
        if file and file.filename:  # Kiểm tra xem file có được chọn không
            # Tạo đường dẫn đầy đủ cho file
            object_key = f"{prefix}{file.filename}"
            s3.upload_fileobj(file, bucket_name, object_key)
            return redirect(url_for('folder', bucket_name=bucket_name, folder_name=folder_name))
        
        # Xử lý tạo thư mục con
        try:
            subfolder_name = request.form.get('folder').strip()
            if subfolder_name:
                subfolder_key = f"{prefix}{subfolder_name}/"
                s3.put_object(Bucket=bucket_name, Key=subfolder_key)
                return redirect(url_for('folder', bucket_name=bucket_name, folder_name=folder_name))
        except:
            return redirect(url_for('folder', bucket_name=bucket_name, folder_name=folder_name))

    return render_template('folder.html', bucket_name=bucket_name, folder_name=folder_name, objects=child_objects, message=message)


# Xóa một đối tượng
@app.route('/delete/<bucket_name>/<path:object_key>', methods=['POST'])
def delete(bucket_name, object_key):
    try:
        s3.delete_object(Bucket=bucket_name, Key=object_key)
    except Exception as e:
        print(f"Error deleting object: {e}")

    # giữ nguyên vị trí tại folder chứa file
    folder_name = '/'.join(object_key.split('/')[:-1])
    if folder_name:
        return redirect(url_for('folder', bucket_name=bucket_name, folder_name=folder_name))
    else:
        return redirect(url_for('objects', bucket_name=bucket_name))


# Xóa một thư mục và các đối tượng bên trong
@app.route('/delete_folder/<bucket_name>/<path:folder_name>', methods=['POST'])
def delete_folder(bucket_name, folder_name):
    try:
        # Lấy danh sách các đối tượng trong thư mục
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=folder_name)
        if 'Contents' in response:
            objects_to_delete = [{'Key': obj['Key']} for obj in response['Contents']]
            if objects_to_delete:
                s3.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_to_delete})
        
        flash(f"Folder '{folder_name}' has been deleted successfully.", 'success')
    except Exception as e:
        print(f"Error deleting folder: {e}")
        flash("An error occurred while deleting the folder.", 'danger')

    # Giữ người dùng ở lại trang hiện tại
    return redirect(request.referrer)  # Quay lại trang trước đó
# Tải về một đối tượng
@app.route('/download/<bucket_name>/<path:object_key>', methods=['GET'])
def download(bucket_name, object_key):
    file_stream = io.BytesIO()
    s3.download_fileobj(bucket_name, object_key, file_stream)
    file_stream.seek(0)
    return send_file(file_stream, as_attachment=True, download_name=object_key)




if __name__ == '__main__':
    app.run(debug=True)