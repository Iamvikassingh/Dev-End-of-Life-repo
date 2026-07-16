module.exports = {
  apps: [
    {
      name: "aws-eol-backend",
      script: "scripts/run-local-backend.py",
      interpreter: "python3",
      cwd: "/home/ubuntu/aws-end-of-life-backend",
      autorestart: true,
      watch: false,
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
}
