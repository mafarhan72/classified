from django.shortcuts import render, redirect
from django.contrib import messages
import uuid
import boto3
from django.conf import settings
from django.core.paginator import Paginator


# Initialize AWS SDK clients
S3_BUCKET_NAME = 'allofcanadaimages'
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
    # 1. Fetch query filtering parameters from URL
    category_filter = request.GET.get('category', 'all')
    location_filter = request.GET.get('location', '').strip().lower()
    sort_filter = request.GET.get('sort', 'latest')
    page_number = request.GET.get('page', 1)

    # 2. Scan entire table from DynamoDB
    try:
        response = table.scan()
        all_items = response.get('Items', [])
    except Exception as e:
        print(f"Error scanning DynamoDB: {e}")
        all_items = []

    # 3. Apply Filters in Python
    filtered_items = []
    for item in all_items:
        # Category Filter matching
        if category_filter != 'all' and item.get('category') != category_filter:
            continue
        
        # Location / City Filter matching (Case-Insensitive substring match)
        if location_filter and location_filter not in item.get('city', '').lower():
            continue
            
        filtered_items.append(item)

    # 4. Apply Sorting
    if sort_filter == 'price_low':
        # Convert numeric string gracefully; items without a clean digit fall to the end
        filtered_items.sort(key=lambda x: float(x.get('price')) if str(x.get('price', '')).isdigit() else float('inf'))
    elif sort_filter == 'price_high':
        filtered_items.sort(key=lambda x: float(x.get('price')) if str(x.get('price', '')).isdigit() else float('-inf'), reverse=True)
    else:
        # Fallback sorting: Defaulting to DynamoDB collection sequence or arbitrary ID sorting
        # Tip: If you choose to add a 'created_at' timestamp to post_ad later, you can sort by that here.
        filtered_items.sort(key=lambda x: x.get('ad_id', ''), reverse=(sort_filter == 'latest'))

    # 5. Paginate items to exactly 20 items max per page
    paginator = Paginator(filtered_items, 20)
    page_obj = paginator.get_page(page_number)

    # 6. Build template context values
    context = {
        'page_obj': page_obj,
        'total_count': len(filtered_items),
    }
    return render(request, "web/ads.html", context)

def ad(request):
    # 1. Capture the unique 'id' string from the query parameters (?id=...)
    ad_id = request.GET.get('id')
    if not ad_id:
        return redirect('ads') # Redirect back to directory if no ID is passed

    # 2. Query DynamoDB using the partition key
    try:
        response = table.get_item(Key={'ad_id': ad_id})
        ad_item = response.get('Item')
    except Exception as e:
        print(f"Error pulling single ad record: {e}")
        ad_item = None

    # 3. Handle cases where the item does not exist
    if not ad_item:
        return redirect('ads')

    # 4. Pass the dictionary data cleanly into your context
    context = {
        'ad': ad_item
    }
    return render(request, "web/ad.html", context)
    

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
        main_file = request.FILES.get('main_image')
        supporting_files = request.FILES.getlist('supporting_images')[:7] # Hard cap at 7 items
        all_uploads = []
        if main_file:
            all_uploads.append(main_file)
        all_uploads.extend(supporting_files)
        
        for index, file_obj in enumerate(all_uploads):
            file_extension = file_obj.name.split('.')[-1]
            
            # Label the main image file explicitly in its S3 path string name
            prefix = "main" if index == 0 else f"support_{index}"
            s3_key = f"ads/{ad_id}/{prefix}_{uuid.uuid4().hex}.{file_extension}"
            
            try:
                s3_client.upload_fileobj(
                    file_obj,
                    S3_BUCKET_NAME,
                    s3_key,
                    ExtraArgs={'ContentType': file_obj.content_type}
                )
                region = s3_client.meta.region_name
                image_url = f"https://{S3_BUCKET_NAME}.s3.{region}.amazonaws.com/{s3_key}"
                image_urls.append(image_url)
                
            except Exception as e:
                print(f"Failed uploading file sequence position {index}: {e}")

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
            messages.success(request, 'Your advertisement has been published successfully!')
            return redirect('post-ad') # Redirect to your ads list page on success
            
        except Exception as e:
            print(f"DynamoDB Insertion Failed: {e}")
            # Optional: Pass an error message context back to your frontend template
            messages.error(request, 'System error: Could not save your listing details.')
            return render(request, 'web/post_ad.html')

    return render(request, 'web/post_ad.html')

