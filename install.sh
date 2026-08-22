#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}📦 Initializing local installation of git-cp-pr...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Error: Python 3 is required but not found on your system.${NC}"
    exit 1
fi

if ! python3 -m pip --version &> /dev/null; then
    echo -e "${RED}❌ Error: python3-pip is required but not found. Please install pip first.${NC}"
    exit 1
fi

echo -e "${BLUE}⚙️  Installing package via pip (user mode)...${NC}"
python3 -m pip install --user --upgrade .

USER_BIN_DIR=$(python3 -m site --user-base)/bin
if [[ ":$PATH:" != *":$USER_BIN_DIR:"* ]]; then
    echo -e "${YELLOW}⚠️ Warning: '$USER_BIN_DIR' is not currently in your \$PATH.${NC}"
    echo -e "To use 'git-cp-pr' globally, add the following line to your ~/.bashrc or ~/.zshrc:"
    echo -e "  ${GREEN}export PATH=\"\$PATH:$USER_BIN_DIR\"${NC}"
fi

echo -e "${GREEN}✨ Installation complete! You can now run 'git-cp-pr' from any repository. 🎉${NC}"
