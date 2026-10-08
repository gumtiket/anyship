"""STS validation only. Credentials never cross the adapter boundary."""
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Protocol
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, CredentialRetrievalError, NoCredentialsError, PartialCredentialsError

from .aws_validation import role_account_id


ERRORS = {
    "access_denied": (403, "역할 ARN, External ID 및 양쪽 계정의 신뢰 정책·AssumeRole 권한을 확인해 주세요."),
    "external_id_not_required": (422, "역할 신뢰 정책이 올바른 External ID를 필수로 요구하도록 수정해 주세요."),
    "account_mismatch": (422, "검증한 AWS 계정과 역할 ARN의 계정이 일치하지 않습니다."),
    "service_credentials_unavailable": (503, "서비스 서버의 AWS 인증 설정을 확인해야 합니다."),
    "aws_unavailable": (503, "AWS 검증을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."),
    "invalid_aws_response": (502, "AWS 역할 검증 응답을 확인할 수 없습니다. 다시 시도해 주세요."),
}


class AwsCheckError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else "aws_unavailable"
        self.status_code, self.message = ERRORS[self.code]
        super().__init__(self.message)


@dataclass(frozen=True)
class AwsIdentity:
    account_id: str


class AwsAdapter(Protocol):
    def check(self, *, role_arn: str, external_id: str, region: str) -> AwsIdentity: ...


class STSAdapter:
    def check(self, *, role_arn: str, external_id: str, region: str) -> AwsIdentity:
        expected = role_account_id(role_arn)
        config = Config(connect_timeout=3, read_timeout=5,
                        retries={"mode": "standard", "total_max_attempts": 2},
                        ignore_configured_endpoint_urls=True)
        try:
            # A fresh session avoids sharing boto3 Sessions between request threads.
            session = boto3.Session()
            with ExitStack() as cleanup:
                sts = session.client("sts", region_name=region, config=config)
                cleanup.callback(sts.close)
                parameters = {"RoleArn": role_arn, "RoleSessionName": "anyship-check-" + uuid.uuid4().hex,
                              "DurationSeconds": 900}
                credentials = sts.assume_role(**parameters, ExternalId=external_id)["Credentials"]
                # Only an explicit AccessDenied proves these negative probes failed as required.
                for extra in ({}, {"ExternalId": "invalid-" + uuid.uuid4().hex}):
                    try:
                        sts.assume_role(**parameters, **extra)
                    except ClientError as error:
                        if error.response.get("Error", {}).get("Code") != "AccessDenied":
                            raise
                    else:
                        raise AwsCheckError("external_id_not_required")
                assumed = session.client(
                    "sts", region_name=region, config=config,
                    aws_access_key_id=credentials["AccessKeyId"],
                    aws_secret_access_key=credentials["SecretAccessKey"],
                    aws_session_token=credentials["SessionToken"],
                )
                cleanup.callback(assumed.close)
                account_id = assumed.get_caller_identity()["Account"]
                if account_id != expected:
                    raise AwsCheckError("account_mismatch")
                return AwsIdentity(account_id=account_id)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code == "AccessDenied":
                raise AwsCheckError("access_denied") from None
            if code in ("ExpiredToken", "InvalidClientTokenId", "SignatureDoesNotMatch"):
                raise AwsCheckError("service_credentials_unavailable") from None
            raise AwsCheckError("aws_unavailable") from None
        except (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError):
            raise AwsCheckError("service_credentials_unavailable") from None
        except BotoCoreError:
            raise AwsCheckError("aws_unavailable") from None
        except (KeyError, TypeError):
            raise AwsCheckError("invalid_aws_response") from None
