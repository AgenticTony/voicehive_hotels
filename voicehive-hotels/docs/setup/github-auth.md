# GitHub Authentication Guide

Since the repository is private, you'll need to authenticate to push. Here are your options:

## Option 1: GitHub Personal Access Token (Recommended)

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Give it a name like "VoiceHive Push"
4. Select scopes:
   - `repo` (full control of private repositories)
5. Generate token and copy it

Then push using:
```bash
git push https://YOUR_GITHUB_USERNAME:YOUR_TOKEN@github.com/AgenticTony/voicehive_hotels.git main
```

## Option 2: SSH Key

1. Check if you have SSH key:
```bash
ls -la ~/.ssh/id_*.pub
```

2. If not, generate one:
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

3. Add to GitHub:
   - Copy key: `pbcopy < ~/.ssh/id_ed25519.pub`
   - Go to GitHub → Settings → SSH and GPG keys
   - Click "New SSH key"
   - Paste and save

4. Change remote to SSH:
```bash
git remote set-url origin git@github.com:AgenticTony/voicehive_hotels.git
git push -u origin main
```

## Option 3: GitHub CLI

1. Install GitHub CLI:
```bash
brew install gh
```

2. Authenticate:
```bash
gh auth login
```

3. Push:
```bash
git push -u origin main
```

## Verify Repository Exists

Double-check the repository URL:
- Should be: https://github.com/AgenticTony/voicehive_hotels
- Make sure you have push access if it's under someone else's account

## If Using Two-Factor Authentication

You must use either:
- Personal Access Token (Option 1)
- SSH Key (Option 2)
- GitHub CLI (Option 3)

Password authentication won't work with 2FA enabled.
