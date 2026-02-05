#!/bin/bash
#
# Gnome Build Script
# Builds the complete macOS app bundle with bundled Python backend.
#
# Usage:
#   ./build.sh          # Build for current architecture (arm64 on Apple Silicon)
#   ./build.sh clean    # Clean build artifacts
#
set -e

echo "================================================"
echo "  Gnome Build Script - macOS Apple Silicon"
echo "================================================"
echo ""

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# Clean command
if [ "$1" == "clean" ]; then
    echo "Cleaning build artifacts..."
    rm -rf dist/
    rm -rf build/
    rm -rf electron/dist/
    rm -rf electron/node_modules/
    echo "Clean complete!"
    exit 0
fi

# Check for required tools
echo "Checking required tools..."

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Please install Python 3.9+"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "ERROR: npm not found. Please install Node.js"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: $PYTHON_VERSION"

# Step 1: Set up virtual environment if needed
echo ""
echo "[Step 1/5] Setting up Python environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

# Step 2: Build Python backend with PyInstaller
echo ""
echo "[Step 2/5] Building Python backend with PyInstaller..."
echo "This may take a few minutes..."

pyinstaller --clean --noconfirm gnome-backend.spec

# Verify the build
if [ ! -f "dist/gnome-backend/gnome-backend" ]; then
    echo "ERROR: PyInstaller build failed - executable not found"
    exit 1
fi

echo "Python backend built successfully!"
echo "  Size: $(du -sh dist/gnome-backend | cut -f1)"

# Step 3: Install Node.js dependencies
echo ""
echo "[Step 3/5] Installing Node.js dependencies..."
cd electron
npm install --silent
cd ..

# Step 4: Create .env file if it doesn't exist
echo ""
echo "[Step 4/5] Checking environment configuration..."
if [ ! -f "electron/.env" ]; then
    if [ -f "electron/.env.example" ]; then
        echo "WARNING: electron/.env not found!"
        echo "Please copy electron/.env.example to electron/.env and add your API keys."
        echo ""
        echo "Required keys:"
        echo "  - VOYAGE_API_KEY"
        echo "  - PINECONE_API_KEY"
        echo "  - PINECONE_HOST"
        echo "  - GOOGLE_CLIENT_ID"
        echo "  - GOOGLE_CLIENT_SECRET"
        echo "  - MICROSOFT_CLIENT_ID"
        echo "  - MICROSOFT_CLIENT_SECRET"
        echo ""
    fi
else
    echo "Environment file found: electron/.env"
fi

# Step 5: Build Electron app
echo ""
echo "[Step 5/5] Building Electron app..."
cd electron

# Build for Apple Silicon (arm64)
npm run build

cd ..

# Summary
echo ""
echo "================================================"
echo "  Build Complete!"
echo "================================================"
echo ""
echo "Output files:"
ls -la electron/dist/*.dmg 2>/dev/null || echo "  (no .dmg found - check electron/dist/)"
echo ""
echo "To test the development version:"
echo "  cd electron && npm start"
echo ""
echo "To install the production version:"
echo "  Open the .dmg file in electron/dist/"
echo ""
