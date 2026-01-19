#!/bin/bash
# Configure one-way nbstripout filter for Jupyter notebooks
# This script configures Git to strip outputs on commit but preserve them on checkout

echo "Configuring nbstripout one-way filter..."

# Check if nbstripout is installed
if ! command -v nbstripout &> /dev/null; then
    echo "❌ nbstripout is not installed"
    echo "Install with: pip install nbstripout"
    exit 1
fi

# Configure one-way filter
git config filter.nbstripout-commit.clean 'nbstripout'
git config filter.nbstripout-commit.smudge 'cat'
git config filter.nbstripout-commit.required true

echo "✅ nbstripout configured successfully"
echo ""
echo "How it works:"
echo "  • On commit: Notebook outputs are stripped (clean)"
echo "  • On checkout: Outputs are preserved (smudge = passthrough)"
echo ""
echo "This prevents repeated cell outputs when pulling changes from agents."
