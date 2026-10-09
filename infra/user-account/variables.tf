# --- 서비스가 반드시 넘겨야 하는 값(기본값 없음) ---

variable "region" {
  description = "기반 인프라를 만들 리전. 등록한 환경의 리전과 같아야 한다."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]$", var.region))
    error_message = "region은 ap-northeast-2 같은 형식이어야 한다."
  }
}

variable "account_id" {
  description = "대상 사용자 계정의 12자리 ID. provider가 이 계정에서만 실행되도록 고정한다."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id는 12자리 숫자여야 한다."
  }
}

variable "env_id" {
  description = "서비스에 등록된 환경 ID. 리소스 이름과 태그에 쓰인다."
  type        = string

  validation {
    # 리소스 이름에 그대로 들어가므로 소문자·숫자·하이픈만 허용한다.
    # 상한 21자는 온프레미스 어댑터(DNS)의 환경 ID 제한과 맞춘 것이다.
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,20}$", var.env_id))
    error_message = "env_id는 소문자, 숫자, 하이픈으로 2~21자여야 한다."
  }
}

variable "service_server_ip" {
  description = "서비스 서버의 탄력적 IP. 호스트의 SSH(22)를 이 주소에만 연다."
  type        = string

  validation {
    condition     = can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}$", var.service_server_ip))
    error_message = "service_server_ip는 단일 IPv4 주소여야 한다(CIDR 아님)."
  }
}

variable "ssh_public_key" {
  description = "서비스 서버 배포 키의 공개 키(ssh-ed25519 ...). 공개 키는 비밀이 아니지만 개인 키는 절대 넣지 않는다."
  type        = string

  validation {
    # 셸 스크립트의 작은따옴표 안에 들어가므로 일부러 엄격하게 검사한다.
    condition     = can(regex("^ssh-ed25519 [A-Za-z0-9+/=]+( [A-Za-z0-9._@-]+)?$", trimspace(var.ssh_public_key)))
    error_message = "ssh_public_key는 \"ssh-ed25519 <key> [comment]\" 형식의 공개 키 한 줄이어야 한다."
  }
}

variable "acme_email" {
  description = "Let's Encrypt 인증서 발급 연락 주소. Traefik 시작에 필수다. 비밀은 아니다."
  type        = string

  validation {
    # .env 파일에 그대로 쓰이므로 공백과 따옴표가 들어갈 수 없게 한다.
    condition     = can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", var.acme_email))
    error_message = "acme_email은 올바른 이메일 주소여야 한다."
  }
}

# --- 기본값이 있는 값(허용 범위를 validation으로 제한) ---

variable "vpc_cidr" {
  description = "새 VPC의 CIDR. 서브넷 4개를 이 안에서 나눈다."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0)) && tonumber(split("/", var.vpc_cidr)[1]) <= 20
    error_message = "vpc_cidr는 올바른 CIDR이고 /20보다 넓거나 같아야 한다."
  }
}

variable "host_instance_type" {
  description = "앱 호스트(EC2) 인스턴스 타입."
  type        = string
  default     = "t3.small"

  validation {
    condition     = contains(["t3.small", "t3.medium", "t3.large"], var.host_instance_type)
    error_message = "host_instance_type은 t3.small, t3.medium, t3.large 중 하나여야 한다."
  }
}

variable "host_volume_size" {
  description = "호스트 루트 볼륨 크기(GiB). 이미지가 쌓이므로 넉넉히 둔다."
  type        = number
  default     = 30

  validation {
    condition     = var.host_volume_size >= 20 && var.host_volume_size <= 100
    error_message = "host_volume_size는 20~100 GiB여야 한다."
  }
}

variable "db_instance_class" {
  description = "RDS PostgreSQL 인스턴스 클래스."
  type        = string
  default     = "db.t4g.micro"

  validation {
    condition     = contains(["db.t4g.micro", "db.t4g.small", "db.t4g.medium"], var.db_instance_class)
    error_message = "db_instance_class는 db.t4g.micro, db.t4g.small, db.t4g.medium 중 하나여야 한다."
  }
}

variable "db_allocated_storage" {
  description = "RDS 스토리지 크기(GiB)."
  type        = number
  default     = 20

  validation {
    condition     = var.db_allocated_storage >= 20 && var.db_allocated_storage <= 100
    error_message = "db_allocated_storage는 20~100 GiB여야 한다."
  }
}
