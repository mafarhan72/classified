from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name="index"),
    path('login/', views.login, name="login"),
    path('register/', views.register, name="register"),
    path('postad/', views.post_ad, name="post-ad"),
    path('ads/', views.ads, name="ads"),
    path('ad/', views.ad, name="ad"),
    path('profile/', views.profile_view, name='profile'),
    path('ad/edit/<str:ad_id>/', views.edit_ad_view, name='edit_ad'),
    path('ad/delete/<str:ad_id>/', views.delete_ad_view, name='delete_ad'),
    path('logout/', views.logout_view, name='logout'),
    
]
