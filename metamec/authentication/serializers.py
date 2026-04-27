from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = (
            "id",
            "full_name",
            "email_address",
            "phone_number",
            "password",
            "agreed_terms_business",
            "agreed_privacy_policy",
        )

    def validate(self, attrs):
        if not attrs.get("agreed_terms_business"):
            raise serializers.ValidationError({"agreed_terms_business": "You must agree to Terms of Business."})


        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email_address = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email_address = attrs.get("email_address")
        password = attrs.get("password")

        user = authenticate(
            request=self.context.get("request"),
            username=email_address,
            password=password,
        )

        if not user:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.is_active:
            raise serializers.ValidationError("Account is inactive.")

        attrs["user"] = user
        return attrs