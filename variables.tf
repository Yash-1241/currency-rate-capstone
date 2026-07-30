variable "aws_region" {
  description = "AWS region. The Learner Lab project is locked to us-east-1."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "This capstone must be deployed in us-east-1."
  }
}

variable "project_name" {
  description = "Short lowercase project name used in AWS resource names."
  type        = string
  default     = "currency-trend-alert"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,30}$", var.project_name))
    error_message = "project_name must be 3-30 characters using lowercase letters, numbers, and hyphens only."
  }
}

variable "environment" {
  description = "Deployment environment suffix."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9-]{2,10}$", var.environment))
    error_message = "environment must use lowercase letters, numbers, and hyphens only."
  }
}

variable "lab_role_name" {
  description = "Existing IAM role supplied by AWS Academy Learner Lab. Terraform will not create an IAM role."
  type        = string
  default     = "LabRole"
}

variable "currency_pairs" {
  description = "Currency pairs to track in BASE/QUOTE format."
  type        = list(string)
  default     = ["EUR/INR", "USD/INR", "GBP/INR"]

  validation {
    condition = length(var.currency_pairs) > 0 && length(var.currency_pairs) <= 10 && alltrue([
      for pair in var.currency_pairs : can(regex("^[A-Za-z]{3}/[A-Za-z]{3}$", trimspace(pair)))
    ])
    error_message = "Provide 1-10 currency pairs in BASE/QUOTE format, for example EUR/INR."
  }
}

variable "alert_threshold_percent" {
  description = "Send an SNS alert when the absolute daily percentage change reaches this value."
  type        = number
  default     = 1.0

  validation {
    condition     = var.alert_threshold_percent > 0 && var.alert_threshold_percent <= 100
    error_message = "alert_threshold_percent must be greater than 0 and at most 100."
  }
}

variable "schedule_expression" {
  description = "EventBridge schedule expression. Default: every day at 07:00 UTC."
  type        = string
  default     = "cron(0 7 * * ? *)"
}

variable "enable_schedule" {
  description = "Enable the daily EventBridge rule. Set false during initial setup if required."
  type        = bool
  default     = true
}

variable "alert_email" {
  description = "Optional email address for SNS alerts. Leave empty to create the topic without an email subscription."
  type        = string
  default     = ""

  validation {
    condition     = var.alert_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be empty or a valid email address."
  }
}

variable "history_retention_days" {
  description = "DynamoDB record retention period. Records expire through TTL after this many days."
  type        = number
  default     = 400

  validation {
    condition     = var.history_retention_days >= 30 && var.history_retention_days <= 3650
    error_message = "history_retention_days must be between 30 and 3650."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention period."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.log_retention_days)
    error_message = "Choose a supported CloudWatch Logs retention value such as 7, 14, 30, 60, 90, 180, or 365."
  }
}
