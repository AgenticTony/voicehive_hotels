#!/bin/bash
# Script to push VoiceHive Hotels to GitHub

echo "Pushing VoiceHive Hotels to GitHub..."

# Verify we're in the right directory
if [ ! -f "WARP.md" ]; then
    echo "Error: Not in VoiceHive Hotels directory"
    exit 1
fi

# Check current remote
echo "Current remote configuration:"
git remote -v

# Push to main branch
echo "Pushing to origin/main..."
git push -u origin main

if [ $? -eq 0 ]; then
    echo "✅ Successfully pushed to GitHub!"
    echo ""
    echo "Repository URL: https://github.com/AgenticTony/voicehive_hotels"
    echo ""
    echo "Next steps:"
    echo "1. Configure repository settings (branch protection, etc.)"
    echo "2. Add collaborators if needed"
    echo "3. Set up GitHub Actions secrets for CI/CD"
    echo "4. Configure LiveKit webhook URL in GitHub secrets"
else
    echo "❌ Push failed. Please ensure:"
    echo "1. The repository exists at https://github.com/AgenticTony/voicehive_hotels"
    echo "2. You have push access to the repository"
    echo "3. Your GitHub credentials are configured"
fi
