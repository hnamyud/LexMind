from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegisterBody(StrictModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=1)


class LoginBody(StrictModel):
    email: EmailStr
    password: str = Field(min_length=8)


class OtpBody(StrictModel):
    email: EmailStr
    otp: str = Field(pattern=r"^\d{6}$")


class SendResetEmailBody(StrictModel):
    email: EmailStr


class ResetPasswordBody(OtpBody):
    new_password: str = Field(alias="newPassword", min_length=8)


class ChangePasswordBody(StrictModel):
    old_password: str = Field(alias="oldPassword", min_length=1)
    new_password: str = Field(alias="newPassword", min_length=6)
    confirm_password: str = Field(alias="confirmPassword", min_length=1)


class UpdateConversationBody(StrictModel):
    title: str = Field(min_length=1)
    summary: str | None = None


class FeedbackBody(StrictModel):
    is_like: bool = Field(alias="isLike")
    reason: str | None = None


class AskBody(StrictModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: str | None = Field(default=None, alias="conversationId")

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        import unicodedata
        cleaned = "".join(char for char in unicodedata.normalize("NFKC", value.strip()) if ord(char) >= 32)
        if not cleaned:
            raise ValueError("String should have at least 2 characters")
        return cleaned


class RunBatchBody(StrictModel):
    dataset_id: str | None = Field(default=None, alias="datasetId")
    dataset_path: str | None = Field(default=None, alias="datasetPath")
    limit: int | None = None
    concurrency: int | None = None
