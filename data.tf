data "aws_caller_identity" "current" {}

data "aws_iam_role" "lab_role" {
  name = var.lab_role_name
}
