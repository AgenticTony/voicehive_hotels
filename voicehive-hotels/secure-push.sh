#!/bin/bash
# Secure push script for VoiceHive Hotels

echo "GitHub Push Script for VoiceHive Hotels"
echo "======================================="
echo ""

# Prompt for username
read -p "Enter your GitHub username: " GITHUB_USERNAME

# Prompt for token (hidden input)
echo "Enter your GitHub Personal Access Token:"
echo "(Input will be hidden for security)"
read -s GITHUB_TOKEN
echo ""

# Verify inputs
if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ Error: Username and token are required"
    exit 1
fi

# Perform the push
echo "Pushing to GitHub..."
git push https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/AgenticTony/voicehive_hotels.git main

# Check result
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Successfully pushed to GitHub!"
    echo ""
    echo "Repository: https://github.com/AgenticTony/voicehive_hotels"
    echo ""
    echo "Next steps:"
    echo "1. Verify the code on GitHub"
    echo "2. Set up GitHub Actions secrets:"
    echo "   - LIVEKIT_API_KEY"
    echo "   - AZURE_OPENAI_API_KEY"
    echo "   - ELEVENLABS_API_KEY"
    echo "3. Configure branch protection rules"
    echo "4. Add collaborators if needed"
else
    echo ""
    echo "❌ Push failed. Please check:"
    echo "1. Your username is correct"
    echo "2. Your token has 'repo' scope"
    echo "3. You have access to the repository"
fi

# Clear sensitive variables
unset GITHUB_TOKEN
unset GITHUB_USERNAME
