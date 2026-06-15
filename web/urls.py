from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name="home"),
    path('login/', views.login, name="login"),
    path('register/', views.register, name="register"),
    path('postad/', views.post_ad, name="post-ad"),
    path('ads/', views.ads, name="ads"),
    path('ad/', views.ad, name="ad"),
    
]
