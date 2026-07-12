from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["personal_id", "first_name", "last_name", "role"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    # No min_length here — DRF's built-in message for it isn't translated.
    # validate_password() below (AUTH_PASSWORD_VALIDATORS) enforces the
    # minimum length instead, with Django's own Hebrew translation.
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["personal_id", "password", "password2", "first_name", "last_name"]
        # Drop the auto-generated UniqueValidator (English, ugly machine
        # translation) in favor of the clean Hebrew message below.
        extra_kwargs = {"personal_id": {"validators": []}}

    def validate_personal_id(self, value):
        if User.objects.filter(personal_id=value).exists():
            raise serializers.ValidationError("מספר אישי זה כבר רשום במערכת.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "הסיסמאות אינן תואמות."})
        validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        validated_data.pop("password2")
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
