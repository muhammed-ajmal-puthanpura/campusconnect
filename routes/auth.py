"""
Authentication Routes - Login, Logout, Registration
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from models.models import User, Role, Department, AppConfig
from models import db
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from datetime import datetime, timedelta
from utils.email_utils import send_email
import os

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        identifier = (request.form.get('identifier') or request.form.get('email') or '').strip()
        password = request.form.get('password')
        
        # Find user: students by username, others by email
        user = None
        user_by_username = User.query.filter_by(username=identifier).first() if identifier else None
        if user_by_username:
            role_name = (user_by_username.role.role_name or '').lower() if user_by_username.role else ''
            if role_name == 'student':
                user = user_by_username
            else:
                flash('Non-students must login with email.', 'error')
                return redirect(url_for('auth.login'))

        if not user:
            user_by_email = User.query.filter_by(email=identifier).first() if identifier else None
            if user_by_email:
                role_name = (user_by_email.role.role_name or '').lower() if user_by_email.role else ''
                if role_name == 'student' and user_by_email.username:
                    flash('Students must login using username.', 'error')
                    return redirect(url_for('auth.login'))
                user = user_by_email

        if user and user.check_password(password):
            # If this is a guest user, block login when expired/archived.
            # Do not affect other roles.
            from datetime import datetime as _dt
            role_name_db = (user.role.role_name or '').strip().lower() if user.role else ''
            is_guest_user = role_name_db == 'guest'
            if is_guest_user:
                # If expiry_date set and in the past, mark expired and prevent login
                if getattr(user, 'expiry_date', None) and user.expiry_date and _dt.utcnow() > user.expiry_date:
                    try:
                        user.guest_status = 'expired'
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    flash('Guest account expired. Please request a new guest account.', 'error')
                    return redirect(url_for('auth.login'))

            # Set session
            session.permanent = True
            session['user_id'] = user.user_id
            session['full_name'] = user.full_name
            session['email'] = user.email
            session['role_id'] = user.role_id
            # Normalize and canonicalize role name for session and redirects
            role_raw = (user.role.role_name or '').strip().lower()
            display_map = {
                'guest': 'Guest',
                'student': 'Student',
                'event organizer': 'Event Organizer',
                'organizer': 'Event Organizer',
                'hod': 'HOD',
                'principal': 'Principal',
                'admin': 'Admin'
            }
            session['role_name'] = display_map.get(role_raw, (user.role.role_name or '').title())
            session['dept_id'] = user.dept_id

            # Redirect based on normalized role
            if role_raw == 'student':
                return redirect(url_for('student.dashboard'))
            elif role_raw in ('event organizer', 'organizer'):
                return redirect(url_for('organizer.dashboard'))
            elif role_raw == 'hod':
                return redirect(url_for('hod.dashboard'))
            elif role_raw == 'principal':
                return redirect(url_for('principal.dashboard'))
            elif role_raw == 'admin':
                return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    guest_enabled = AppConfig.query.get('guest_enabled')
    return render_template('auth/login.html', guest_enabled=guest_enabled)



    # Mobile/SMS guest login removed — use email guest links only.


@bp.route('/guest/email', methods=['GET', 'POST'])
def guest_email_request():
    """Request a guest login link via email."""
    cfg = AppConfig.query.get('guest_enabled')
    if not cfg or cfg.value != '1':
        flash('Guest login is disabled', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email or '@' not in email:
            flash('Please provide a valid email address', 'error')
            return redirect(url_for('auth.guest_email_request'))

        # If this email already belongs to a non-guest user, do not send a guest login link.
        existing = User.query.filter_by(email=email).first()
        if existing:
            role_name_db = (existing.role.role_name or '').strip().lower() if existing.role else ''
            if role_name_db != 'guest':
                flash('This email is already registered. Please login using your account.', 'warning')
                return redirect(url_for('auth.login'))

        # Generate signed token and send email
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = serializer.dumps({'email': email, 'purpose': 'guest_email_login'}, salt='guest-email')
        verify_url = url_for('auth.guest_email_verify', token=token, _external=True)

        subject = 'Your Guest Login Link'
        # Plain text fallback and HTML email with a button for Gmail / clients that render HTML
        body = (
            f'Hello,\n\nUse the link below to login as a guest (valid for 15 minutes):\n\n{verify_url}\n\nIf you did not request this, ignore this email.'
        )
        html_body = f"""
        <html>
          <body>
            <p>Hello,</p>
            <p>Click the button below to login as a guest (valid for 15 minutes):</p>
            <p><a href=\"{verify_url}\" style=\"display:inline-block;padding:12px 20px;background-color:#1a73e8;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;\">Login as Guest</a></p>
            <p>If the button doesn't work, copy and paste this link into your browser:</p>
            <p><a href=\"{verify_url}\">{verify_url}</a></p>
            <p>If you did not request this, ignore this email.</p>
          </body>
        </html>
        """
        try:
            send_email(email, subject, body, html_body=html_body)
            flash('A login link has been sent to your email address.', 'success')
        except Exception:
            current_app.logger.exception('Failed to send guest login email')
            flash('Failed to send email. Please contact the administrator.', 'error')

        return redirect(url_for('auth.login'))

    return render_template('auth/guest_email_request.html')


@bp.route('/guest/email/verify')
def guest_email_verify():
    """Verify the guest email token and create/login guest user."""
    token = request.args.get('token')
    if not token:
        flash('Missing token', 'error')
        return redirect(url_for('auth.login'))

    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(token, salt='guest-email', max_age=900)
    except SignatureExpired:
        flash('Login link expired', 'error')
        return redirect(url_for('auth.guest_email_request'))
    except Exception:
        flash('Invalid login link', 'error')
        return redirect(url_for('auth.login'))

    email = data.get('email')
    if not email:
        flash('Invalid token payload', 'error')
        return redirect(url_for('auth.login'))

    # Find or create guest user by email
    user = User.query.filter_by(email=email).first()
    if user:
        role_name_db = (user.role.role_name or '').strip().lower() if user.role else ''
        if role_name_db != 'guest':
            # This email belongs to a normal user (admin/student/etc) — do not allow guest login.
            flash('This email is registered with an existing account. Please login with your credentials.', 'warning')
            return redirect(url_for('auth.login'))
    guest_role = Role.query.filter(Role.role_name.ilike('guest')).first()
    student_role = Role.query.filter(Role.role_name.ilike('student')).first()

    if not user:
        validity_days = 30
        vcfg = AppConfig.query.get('guest_validity_days')
        if vcfg and vcfg.value and vcfg.value.isdigit():
            validity_days = int(vcfg.value)
        expiry = datetime.utcnow() + timedelta(days=validity_days)
        assigned_role_id = guest_role.role_id if guest_role else (student_role.role_id if student_role else 1)

        user = User(
            full_name=f'Guest {email.split("@")[0]}',
            username=None,
            email=email,
            role_id=assigned_role_id,
            dept_id=None,
        )
        user.set_password(__import__('uuid').uuid4().hex)
        user.expiry_date = expiry
        user.guest_status = 'active'
        # generate a short unique guest username like G-XXXXXXXX
        import uuid
        def make_code():
            return f"G-{uuid.uuid4().hex[:8].upper()}"
        code = make_code()
        from models.models import User as _U
        while _U.query.filter_by(username=code).first():
            code = make_code()
        user.username = code
        db.session.add(user)
        db.session.commit()
    else:
        # existing user
        # ensure existing guest has a username we can use as Guest ID
        if not user.username:
            import uuid
            def make_code():
                return f"G-{uuid.uuid4().hex[:8].upper()}"
            code = make_code()
            from models.models import User as _U
            while _U.query.filter_by(username=code).first():
                code = make_code()
            user.username = code
            db.session.commit()
        if user.expiry_date and datetime.utcnow() > user.expiry_date:
            user.guest_status = 'expired'
            db.session.commit()
            flash('Guest account expired. Please request a new guest account.', 'error')
            return redirect(url_for('auth.guest_email_request'))

    # Create session for guest user
    session.permanent = True
    session['user_id'] = user.user_id
    session['full_name'] = user.full_name
    session['email'] = user.email
    session['role_id'] = user.role_id
    session['role_name'] = 'Guest'
    session['dept_id'] = user.dept_id
    # Keep a session flag for compatibility
    session['is_guest'] = True if (user.role and (user.role.role_name or '').strip().lower() == 'guest') else False
    # store guest identifier in session (username acts as Guest ID)
    session['guest_code'] = user.username
    session['username'] = user.username
    return redirect(url_for('student.dashboard'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if session.get('role_name', '').lower() != 'admin':
        flash('Registration is disabled. Please contact the administrator.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        full_name = request.form.get('full_name')
        username = (request.form.get('username') or '').strip()
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role_id = request.form.get('role_id')
        dept_id = request.form.get('dept_id')
        
        # Validation
        if len(password or '') < 8:
            flash('Password must be at least 8 characters.', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))
        
        # Check if email exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('auth.register'))

        if username and User.query.filter_by(username=username).first():
            flash('Username already registered', 'error')
            return redirect(url_for('auth.register'))
        
        # Create user
        user = User(
            full_name=full_name,
            username=username or None,
            email=email,
            role_id=int(role_id),
            dept_id=int(dept_id) if dept_id else None
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))
    
    # Get roles and departments for form
    roles = Role.query.all()
    departments = Department.query.all()
    
    return render_template('auth/register.html', roles=roles, departments=departments)


@bp.route('/logout')
def logout():
    """User logout"""
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('auth.login'))

@bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """Signup disabled — redirect to login."""
    flash('Registration is disabled. Please contact the administrator.', 'warning')
    return redirect(url_for('auth.login'))

@bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    """Change password for logged-in users"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    # Prevent guest users from using the change-password feature
    if session.get('is_guest') or (session.get('role_name') or '').strip().lower() == 'guest':
        flash('Guest accounts cannot change password.', 'warning')
        return redirect(url_for('common.profile'))
    
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        user = User.query.get(session['user_id'])
        
        if not user or not user.check_password(old_password):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('auth.change_password'))
        
        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('auth.change_password'))
        
        if len(new_password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return redirect(url_for('auth.change_password'))
        
        user.set_password(new_password)
        db.session.commit()
        flash('Password changed successfully.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/change_password.html')


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request a password reset link"""
    if request.method == 'POST':
        identifier = (request.form.get('identifier') or request.form.get('email') or '').strip()

        user = None
        if identifier:
            user = User.query.filter_by(email=identifier).first()
            if not user:
                user = User.query.filter_by(username=identifier).first()

        # Always show the same response to prevent user enumeration
        if user:
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = serializer.dumps({'user_id': user.user_id}, salt='password-reset')
            reset_url = url_for('auth.reset_password', token=token, _external=True)

            subject = 'Reset your Campus Events password'
            body = (
                f"Hello {user.full_name},\n\n"
                "We received a request to reset your password. "
                "Use the link below to set a new password (valid for 60 minutes):\n\n"
                f"{reset_url}\n\n"
                "If you didn't request this, you can ignore this email."
            )
            # Attempt to send the reset email. Do not reveal account existence to the requester.
            try:
                if user.email:
                    send_email(user.email, subject, body)
                else:
                    # No email configured for this user; log the reset URL for administrator debugging
                    current_app.logger.info(f"Password reset URL for user_id={user.user_id}: {reset_url}")
            except Exception:
                current_app.logger.exception('Failed to send password reset email')

            # Always show the same generic message to avoid account enumeration
            flash('If an account with that identifier exists, a password reset link has been sent to the registered email address.', 'info')
            return redirect(url_for('auth.login'))
            
    return render_template('auth/forgot_password.html')


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password using a token"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(token, salt='password-reset', max_age=3600)
        user_id = data.get('user_id')
    except SignatureExpired:
        flash('Reset link has expired. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('Invalid reset link. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.get(user_id)
    if not user:
        flash('Invalid reset link. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if len(new_password or '') < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return redirect(url_for('auth.reset_password', token=token))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.reset_password', token=token))

        user.set_password(new_password)
        db.session.commit()
        flash('Password reset successfully. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)
