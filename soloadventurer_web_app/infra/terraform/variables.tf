variable "project" {
  type    = string
  default = "soloadventurer"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
}

variable "callback_urls" {
  type    = list(string)
  default = ["http://localhost:3000"]
}