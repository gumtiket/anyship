"""Names of the pre-built deployment sets. They match the names the AI side
(AI/ai/src/ai/spec) uses when it selects a set, so a selection can be passed
straight to an adapter."""
from typing import Literal

SetName = Literal["aws-serverless", "aws-always-on", "onprem"]

AWS_SERVERLESS: SetName = "aws-serverless"  # Lambda + Function URL
AWS_ALWAYS_ON: SetName = "aws-always-on"  # shared EC2 host + Compose + Traefik
ONPREM: SetName = "onprem"  # SSH + Compose + Traefik on the user's own server

SET_NAMES: tuple[SetName, ...] = (AWS_SERVERLESS, AWS_ALWAYS_ON, ONPREM)
