#!/bin/bash
echo "================================================"
echo "Campus Event Management System"
echo "================================================"
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt --break-system-packages --quiet

echo ""
echo "Starting Flask application..."
echo "Access the application at: http://localhost:5000"
echo ""
echo "Demo Credentials:"
echo "  Admin: admin@campus.edu / admin123"
echo "  Principal: principal@campus.edu / principal123"
echo "  HOD: hod.cs@campus.edu / hod123"
echo "  Organizer: organizer1@campus.edu / org123"
echo "  Student: alice@campus.edu / student123"
echo ""
echo "Press Ctrl+C to stop the server"
echo "================================================"
echo ""

python app.py
