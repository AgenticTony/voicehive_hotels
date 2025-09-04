#!/bin/bash
# Setup SSH for GitHub

echo "GitHub SSH Setup"
echo "==============="

# Check for existing SSH key
if [ -f ~/.ssh/id_ed25519.pub ]; then
    echo "✅ SSH key already exists"
    echo "Current key:"
    cat ~/.ssh/id_ed25519.pub
else
    echo "Creating new SSH key..."
    read -p "Enter your email: " EMAIL
    ssh-keygen -t ed25519 -C "$EMAIL" -f ~/.ssh/id_ed25519
    
    echo "✅ SSH key created"
fi

# Start ssh-agent
eval "$(ssh-agent -s)"

# Add key to ssh-agent
ssh-add ~/.ssh/id_ed25519

# Copy public key
echo ""
echo "📋 Your public key has been copied to clipboard!"
pbcopy < ~/.ssh/id_ed25519.pub

echo ""
echo "Next steps:"
echo "1. Go to: https://github.com/settings/keys"
echo "2. Click 'New SSH key'"
echo "3. Paste the key (already in your clipboard)"
echo "4. Save the key"
echo ""
echo "Then change your remote to SSH:"
echo "git remote set-url origin git@github.com:AgenticTony/voicehive_hotels.git"
echo ""
echo "Now you can push without entering credentials:"
echo "git push origin main"
