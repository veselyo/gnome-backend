#!/bin/bash
# Post-install script to remove quarantine from Gnome.app

echo "Removing quarantine attribute from Gnome..."
xattr -cr /Applications/Gnome.app 2>/dev/null || true

echo "Gnome installed successfully!"
exit 0

