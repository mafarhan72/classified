from django.shortcuts import render, redirect
import uuid
import boto3
from django.conf import settings


# Initialize AWS SDK clients
S3_BUCKET_NAME = 'your-s3-bucket-name'
DYNAMODB_TABLE_NAME = 'ads_data'

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

# Create your views here.

def index(request):
    return render(request,"web/index.html")

def login(request):
    return render(request,"web/login.html")

def ads(request):
    return render(request,"web/ads.html")

def ad(request):
    return render(request,"web/ad.html")
    

def register(request):
    return render(request,"web/register.html")


def post_ad(request):
    if request.method == 'POST':
        # 1. Generate a unique ID for the advertisement
        ad_id = str(uuid.uuid4())
        
        # 2. Extract text fields from the form
        category = request.POST.get('category')
        title = request.POST.get('title')
        price = request.POST.get('price') or "N/A"
        description = request.POST.get('description')
        city = request.POST.get('city')
        zip_code = request.POST.get('zip_code')
        address = request.POST.get('address') or ""
        contact_name = request.POST.get('contact_name')
        contact_email = request.POST.get('contact_email')
        contact_mobile = request.POST.get('contact_mobile')
        
        # 3. Handle up to 8 image uploads to S3
        image_urls = []
        uploaded_files = request.FILES.getlist('images')[:8] # Force cap at 8 files
        
        for index, file_obj in enumerate(uploaded_files):
            # Generate a unique key name inside an "ads/" folder in S3
            file_extension = file_obj.name.split('.')[-1]
            s3_key = f"ads/{ad_id}/{index}_{uuid.uuid4().hex}.{file_extension}"
            
            try:
                # Upload file to S3
                s3_client.upload_fileobj(
                    file_obj,
                    S3_BUCKET_NAME,
                    s3_key,
                    ExtraArgs={
                        'ContentType': file_obj.content_type
                    }
                )
                # Construct the public URL of the uploaded image
                # Note: Assumes your S3 bucket has public read policies enabled
                region = s3_client.meta.region_name
                image_url = f"https://{S3_BUCKET_NAME}.s3.{region}.amazonaws.com/{s3_key}"
                image_urls.append(image_url)
                
            except Exception as e:
                # Log or handle upload failure gracefully
                print(f"Failed to upload image {index}: {e}")

        # 4. Save metadata and S3 URLs directly to DynamoDB
        try:
            table.put_item(
                Item={
                    'ad_id': ad_id,          # Partition Key
                    'category': category,
                    'title': title,
                    'price': price,
                    'description': description,
                    'city': city,
                    'zip_code': zip_code,
                    'address': address,
                    'contact_name': contact_name,
                    'contact_email': contact_email,
                    'contact_mobile': contact_mobile,
                    'image_urls': image_urls, # Stored as a String List attribute
                }
            )
            return redirect('home') # Redirect to your ads list page on success
            
        except Exception as e:
            print(f"DynamoDB Insertion Failed: {e}")
            # Optional: Pass an error message context back to your frontend template
            return render(request, 'post_ad.html', {'error': 'Failed to save ad details.'})

    return render(request, 'post_ad.html')

