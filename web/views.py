from django.shortcuts import render, redirect
from django.contrib import messages
import uuid
import boto3
from django.conf import settings
from django.core.paginator import Paginator
from django.contrib.auth.hashers import make_password, check_password


# Initialize AWS SDK clients
S3_BUCKET_NAME = 'allofcanadaimages'
DYNAMODB_TABLE_NAME = 'ads_data'

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('ads_data')
users_table = dynamodb.Table('users_data')

# Create your views here.

def register(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email').strip().lower()
        mobile = request.POST.get('mobile').strip()
        password = request.POST.get('password')
        terms = request.POST.get('terms')

        if not terms:
            messages.error(request, "You must accept the Terms of Service to create an account.")
            return render(request, "web/register.html")

        try:
            existing_user = users_table.get_item(Key={'email': email})
            if 'Item' in existing_user:
                messages.error(request, "An account with this email address already exists.")
                return render(request, "web/register.html")

            hashed_password = make_password(password)

            users_table.put_item(
                Item={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'mobile': mobile,
                    'password': hashed_password,
                }
            )

            # UPDATED FLOW: Dropped auto-login sessions, send to login instead
            messages.success(request, 'Registration successful! Please log in with your new credentials below.')
            return redirect('login') # Redirects to login view name

        except Exception as e:
            print(f"Registration Failed: {e}")
            messages.error(request, "Registration system error. Please try again.")
            
    return render(request, "web/register.html")

def get_current_user_email(request):
    # Adjust this if you use request.session['user_email'] instead of Django Auth
    return request.user.email if request.user.is_authenticated else request.session.get('user_email')

def index(request):
    return render(request,"web/index.html")

def login(request):
    if request.method == 'POST':
        username_input = request.POST.get('username').strip().lower()
        password_input = request.POST.get('password')

        try:
            user_item = None
            
            # Since user can input Email OR Mobile, we verify formats
            if "@" in username_input:
                # Direct read optimization using Partition Key lookup
                response = users_table.get_item(Key={'email': username_input})
                user_item = response.get('Item')
            else:
                # Secondary lookup check via Scan for matching mobile strings
                response = users_table.scan(
                    FilterExpression=boto3.dynamodb.conditions.Attr('mobile').eq(username_input)
                )
                items = response.get('Items', [])
                if items:
                    user_item = items[0]

            # Verify password match string against hashed value
            if user_item and check_password(password_input, user_item['password']):
                # Save data to cookie session middleware parameters
                request.session['user_email'] = user_item['email']
                request.session['user_name'] = f"{user_item['first_name']} {user_item['last_name']}"
                
                # 🌟 ADDED: Cache initial ad count on login to lock navigation limits
                try:
                    ad_response = table.scan(
                        FilterExpression=boto3.dynamodb.conditions.Attr('owner_email').eq(user_item['email'])
                    )
                    request.session['ad_count'] = len(ad_response.get('Items', []))
                except Exception as ad_error:
                    print(f"Failed scanning background ad counts during authorization: {ad_error}")
                    request.session['ad_count'] = 0
                
                messages.success(request, "Logged in successfully.")
                return redirect('profile')
            else:
                messages.error(request, "Invalid credentials matching Email/Mobile or Password combinations.")
                
        except Exception as e:
            print(f"Login Failure: {e}")
            messages.error(request, "Authentication system timed out.")

    return render(request, "web/login.html")


# 3. USER LOGOUT ROUTE (Bonus helper to clear down session states)
def logout_view(request):
    request.session.flush() # Completely wipes out active user session dictionary keys
    messages.success(request, "Logged out successfully.")
    return redirect('login')

def ads(request):
    # 1. Fetch query filtering and text search parameters from URL
    category_filter = request.GET.get('category', 'all')
    location_filter = request.GET.get('location', '').strip().lower()
    sort_filter = request.GET.get('sort', 'latest')
    search_query = request.GET.get('q', '').strip().lower() # 🌟 NEW: Capture search keywords
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
            
        # 🌟 NEW: Text Search Filter (Matches Title OR Description)
        if search_query:
            title_match = search_query in item.get('title', '').lower()
            desc_match = search_query in item.get('description', '').lower()
            if not (title_match or desc_match):
                continue
            
        filtered_items.append(item)

    # 4. Apply Sorting
    if sort_filter == 'price_low':
        filtered_items.sort(key=lambda x: float(x.get('price')) if str(x.get('price', '')).isdigit() else float('inf'))
    elif sort_filter == 'price_high':
        filtered_items.sort(key=lambda x: float(x.get('price')) if str(x.get('price', '')).isdigit() else float('-inf'), reverse=True)
    else:
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
    

def post_ad(request):
    # 1. Ensure the user is logged in
    user_email = get_current_user_email(request)
    if not user_email:
        messages.error(request, "Please log in to your account to post an advertisement.")
        return redirect('login')
        
    if request.method == 'POST':
        # 2. Enforce the 3 ads maximum limit tracking by OWNER account email
        try:
            response = table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('owner_email').eq(user_email)
            )
            if len(response.get('Items', [])) >= 3:
                messages.error(request, 'Hold on! You have reached your maximum limit of 3 posted ads.')
                return render(request, 'web/post_ad.html')
        except Exception as e:
            print(f"Error checking ad limit: {e}")

        # 3. Generate unique item ID
        ad_id = str(uuid.uuid4())
        
        # 4. Extract text fields from the form submission
        category = request.POST.get('category')
        title = request.POST.get('title')
        price = request.POST.get('price') or "N/A"
        description = request.POST.get('description')
        city = request.POST.get('city')
        zip_code = request.POST.get('zip_code')
        address = request.POST.get('address') or ""
        contact_name = request.POST.get('contact_name')
        
        # This keeps whatever email they typed into the form as the public contact email
        contact_email = request.POST.get('contact_email')
        contact_mobile = request.POST.get('contact_mobile')
        
        # 5. Handle optional image uploads to S3
        image_urls = []
        main_file = request.FILES.get('main_image')
        supporting_files = request.FILES.getlist('supporting_images')[:7]
        
        all_uploads = []
        if main_file:
            all_uploads.append(main_file)
        all_uploads.extend(supporting_files)
        
        for index, file_obj in enumerate(all_uploads):
            file_extension = file_obj.name.split('.')[-1]
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
                print(f"Failed uploading image sequence position {index}: {e}")

        # 6. Save metadata directly to DynamoDB with hidden ownership link
        try:
            table.put_item(
                Item={
                    'ad_id': ad_id,
                    'owner_email': user_email,     # 🌟 FIXED: Tracks who owns the post behind the scenes
                    'category': category,
                    'title': title,
                    'price': price,
                    'description': description,
                    'city': city,
                    'zip_code': zip_code,
                    'address': address,
                    'contact_name': contact_name,
                    'contact_email': contact_email, # 🌟 FLEXIBLE: Displays whatever custom email they input
                    'contact_mobile': contact_mobile,
                    'image_urls': image_urls,
                }
            )
            messages.success(request, 'Your advertisement has been published successfully!')
            request.session['ad_count'] = request.session.get('ad_count', 0) + 1 # 🌟 ADD THIS LINE HERE
            return redirect(f"/ad/?id={ad_id}")
            
        except Exception as e:
            print(f"DynamoDB Insertion Failed: {e}")
            messages.error(request, 'System error: Could not save your listing details.')
            return render(request, 'web/post_ad.html')

    return render(request, 'web/post_ad.html')


def profile_view(request):
    user_email = get_current_user_email(request)
    if not user_email:
        return redirect('login')

    # Query items that match the logged-in user account owner field
    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('owner_email').eq(user_email)
        )
        user_ads = response.get('Items', [])
        request.session['ad_count'] = len(user_ads)
    except Exception as e:
        print(f"Error fetching user ads: {e}")
        user_ads = []

    context = {
        'user_ads': user_ads,
        'ad_count': len(user_ads),
        'session_user_name': request.session.get('user_name', 'User'),
        'session_user_email': user_email,
    }
    return render(request, 'web/profile.html', context)


# 2. ENFORCE LIMIT IN POST AD VIEW (Add this block inside your existing post_ad view)
# Place this immediately inside your `if request.method == 'POST':` block before uploading images:
"""
user_email = get_current_user_email(request)
response = table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('contact_email').eq(user_email))
if len(response.get('Items', [])) >= 3:
    messages.error(request, 'Hold on! You have reached your maximum limit of 3 posted ads.')
    return render(request, 'web/post_ad.html')
"""


# 3. EDIT AD VIEW
def edit_ad_view(request, ad_id):
    user_email = get_current_user_email(request)
    if not user_email:
        return redirect('login')

    try:
        response = table.get_item(Key={'ad_id': ad_id})
        ad_item = response.get('Item')
    except Exception as e:
        return redirect('profile')

    if not ad_item:
        return redirect('profile')

    # SECURED: Verify that the background account owner matches the person editing
    if ad_item.get('owner_email') != user_email:
        messages.error(request, "Access Denied: You do not have permission to edit this listing.")
        return redirect('profile')

    if request.method == 'POST':
        try:
            table.update_item(
                Key={'ad_id': ad_id},
                UpdateExpression="set title=:t, price=:p, description=:d, city=:c, zip_code=:z, address=:a",
                ExpressionAttributeValues={
                    ':t': request.POST.get('title'),
                    ':p': request.POST.get('price') or "N/A",
                    ':d': request.POST.get('description'),
                    ':c': request.POST.get('city'),
                    ':z': request.POST.get('zip_code'),
                    ':a': request.POST.get('address') or "",
                }
            )
            messages.success(request, 'Your advertisement was updated successfully.')
            return redirect('profile')
        except Exception as e:
            messages.error(request, 'Failed to save changes.')
            
    return render(request, 'web/edit_ad.html', {'ad': ad_item})


def delete_ad_view(request, ad_id):
    user_email = get_current_user_email(request)
    if not user_email:
        return redirect('login')

    try:
        response = table.get_item(Key={'ad_id': ad_id})
        ad_item = response.get('Item')
        
        if not ad_item:
            messages.error(request, "Advertisement not found.")
            return redirect('profile')
            
        # SECURED: Verify that the background account owner matches the person deleting
        if ad_item.get('owner_email') != user_email:
            messages.error(request, "Access Denied: You do not have permission to delete this listing.")
            return redirect('profile')

        table.delete_item(Key={'ad_id': ad_id})
        messages.success(request, 'Your advertisement has been removed permanently.')
        request.session['ad_count'] = max(0, request.session.get('ad_count', 1) - 1) # 🌟 ADD THIS LINE HERE
        return redirect('profile')
        
    except Exception as e:
        messages.error(request, 'Failed to delete advertisement.')
        
    return redirect('profile')
