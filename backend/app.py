import os, secrets, io, smtplib, unicodedata, json
from email.message import EmailMessage

# Canonical HUB origin: account tokens must never be linked to another application.
HUB_APP_URL="https://hub.bim-soignies.be"
SESSION_DAYS=90
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS, cross_origin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from openpyxl import load_workbook, Workbook
from cryptography.fernet import Fernet, InvalidToken

db=SQLAlchemy()

class Member(db.Model):
    __tablename__="members"
    id=db.Column(db.Integer,primary_key=True)
    first_name=db.Column(db.String(100),nullable=False)
    last_name=db.Column(db.String(100),nullable=False)
    company=db.Column(db.String(180))
    activity=db.Column(db.String(180))
    email=db.Column(db.String(180),index=True)
    phone=db.Column(db.String(50))
    network_type=db.Column(db.String(30),nullable=False,default="OFFICIAL_BNI",index=True)
    network_access_enabled=db.Column(db.Boolean,nullable=False,default=False,index=True)
    alumni_bridge_enabled=db.Column(db.Boolean,nullable=False,default=False)
    alumni_requested_at=db.Column(db.DateTime)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class UserAccount(db.Model):
    __tablename__="user_accounts"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,unique=True,index=True)
    email=db.Column(db.String(180),nullable=False,unique=True,index=True)
    password_hash=db.Column(db.String(255))
    status=db.Column(db.String(30),nullable=False,default="INVITED")
    invitation_token=db.Column(db.String(128),unique=True,index=True)
    invitation_expires_at=db.Column(db.DateTime)
    password_reset_token=db.Column(db.String(128),unique=True,index=True)
    password_reset_expires_at=db.Column(db.DateTime)
    activated_at=db.Column(db.DateTime)
    is_system_admin=db.Column(db.Boolean,nullable=False,default=False)
    member=db.relationship("Member",backref=db.backref("user_account",uselist=False))

class AuthSession(db.Model):
    __tablename__="auth_sessions"
    id=db.Column(db.Integer,primary_key=True)
    account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),nullable=False,index=True)
    support_actor_id=db.Column(db.Integer,nullable=True)
    support_parent_id=db.Column(db.Integer,nullable=True)
    token_hash=db.Column(db.String(64),nullable=False,unique=True,index=True)
    expires_at=db.Column(db.DateTime,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    account=db.relationship("UserAccount")

class Membership(db.Model):
    __tablename__="memberships"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    start_date=db.Column(db.Date)
    end_date=db.Column(db.Date)
    status=db.Column(db.String(30),nullable=False,default="ACTIVE")
    member=db.relationship("Member",backref="memberships")

class MemberNetworkHistory(db.Model):
    __tablename__="member_network_history"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    network_type=db.Column(db.String(30),nullable=False,index=True)
    start_date=db.Column(db.Date,nullable=False,default=date.today)
    end_date=db.Column(db.Date)
    changed_by_account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),nullable=True,index=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class NotificationRepairRun(db.Model):
    __tablename__="notification_repair_runs"
    key=db.Column(db.String(100),primary_key=True)
    report=db.Column(db.Text,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class FeatureFlag(db.Model):
    __tablename__="feature_flags"
    key=db.Column(db.String(80),primary_key=True)
    label=db.Column(db.String(180),nullable=False)
    description=db.Column(db.Text)
    enabled=db.Column(db.Boolean,nullable=False,default=False)
    updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)

class OffMembership(db.Model):
    __tablename__="off_memberships"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    plan_code=db.Column(db.String(30),nullable=False,index=True)
    status=db.Column(db.String(30),nullable=False,default="OFFERED",index=True)
    trial_number=db.Column(db.Integer,nullable=False,default=1)
    starts_at=db.Column(db.Date)
    ends_at=db.Column(db.Date)
    offered_by_account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),nullable=True,index=True)
    note=db.Column(db.Text)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)
    updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)

class AuditLog(db.Model):
    __tablename__="audit_logs"
    id=db.Column(db.Integer,primary_key=True)
    account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),index=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),index=True)
    action=db.Column(db.String(100),nullable=False,index=True)
    entity_type=db.Column(db.String(80),index=True)
    entity_id=db.Column(db.String(80))
    details=db.Column(db.Text)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class HandoverItem(db.Model):
    __tablename__="handover_items"
    id=db.Column(db.Integer,primary_key=True)
    from_mandate_id=db.Column(db.Integer,db.ForeignKey("mandates.id"),nullable=False,index=True)
    to_mandate_id=db.Column(db.Integer,db.ForeignKey("mandates.id"),nullable=False,index=True)
    role_id=db.Column(db.Integer,db.ForeignKey("roles.id"),nullable=False,index=True)
    title=db.Column(db.String(255),nullable=False)
    notes=db.Column(db.Text)
    outgoing_confirmed_at=db.Column(db.DateTime)
    incoming_confirmed_at=db.Column(db.DateTime)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class Resource(db.Model):
    __tablename__="resources"
    id=db.Column(db.Integer,primary_key=True)
    title=db.Column(db.String(255),nullable=False)
    description=db.Column(db.Text)
    category=db.Column(db.String(60),nullable=False,default="GENERAL")
    url=db.Column(db.Text)
    role_id=db.Column(db.Integer,db.ForeignKey("roles.id"),nullable=True,index=True)
    board_only=db.Column(db.Boolean,nullable=False,default=False)
    active=db.Column(db.Boolean,nullable=False,default=True)
    file_name=db.Column(db.String(255))
    file_type=db.Column(db.String(120))
    file_data=db.Column(db.LargeBinary)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class ChapterDocument(db.Model):
    __tablename__="chapter_documents"
    id=db.Column(db.Integer,primary_key=True)
    mandate_id=db.Column(db.Integer,db.ForeignKey("mandates.id"),nullable=False,index=True)
    uploaded_by_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=True,index=True)
    title=db.Column(db.String(255),nullable=False)
    description=db.Column(db.Text)
    category=db.Column(db.String(80),nullable=False,default="AUTRE")
    file_name=db.Column(db.String(255),nullable=False)
    file_type=db.Column(db.String(120))
    file_data=db.Column(db.LargeBinary,nullable=False)
    active=db.Column(db.Boolean,nullable=False,default=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class Platform(db.Model):
    __tablename__="platforms"
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(180),nullable=False)
    description=db.Column(db.Text)
    url=db.Column(db.Text)
    owner_role_id=db.Column(db.Integer,db.ForeignKey("roles.id"),nullable=True,index=True)
    board_only=db.Column(db.Boolean,nullable=False,default=False)
    renewal_info=db.Column(db.String(255))
    active=db.Column(db.Boolean,nullable=False,default=True)

class VaultEntry(db.Model):
    __tablename__="vault_entries"
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(180),nullable=False)
    url=db.Column(db.Text)
    username_encrypted=db.Column(db.LargeBinary)
    password_encrypted=db.Column(db.LargeBinary)
    notes_encrypted=db.Column(db.LargeBinary)
    active=db.Column(db.Boolean,nullable=False,default=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)

class Mentorship(db.Model):
    __tablename__="mentorships"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    mentor_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    status=db.Column(db.String(30),nullable=False,default="ACTIVE")
    started_at=db.Column(db.Date,default=date.today)
    completed_at=db.Column(db.Date)

class OnboardingStep(db.Model):
    __tablename__="onboarding_steps"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    code=db.Column(db.String(60),nullable=False)
    label=db.Column(db.String(180),nullable=False)
    completed=db.Column(db.Boolean,nullable=False,default=False)
    completed_at=db.Column(db.DateTime)

class Mandate(db.Model):
    __tablename__="mandates"
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),nullable=False)
    start_date=db.Column(db.Date,nullable=False)
    end_date=db.Column(db.Date,nullable=False)
    status=db.Column(db.String(30),nullable=False,default="PREPARATION")

class Role(db.Model):
    __tablename__="roles"
    id=db.Column(db.Integer,primary_key=True)
    name=db.Column(db.String(120),nullable=False,unique=True)

class RoleAssignment(db.Model):
    __tablename__="role_assignments"
    id=db.Column(db.Integer,primary_key=True)
    mandate_id=db.Column(db.Integer,db.ForeignKey("mandates.id"),nullable=False)
    role_id=db.Column(db.Integer,db.ForeignKey("roles.id"),nullable=False)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False)
    status=db.Column(db.String(30),nullable=False,default="ACTIVE")

class ImportLog(db.Model):
    __tablename__="import_logs"
    id=db.Column(db.Integer,primary_key=True)
    account_id=db.Column(db.Integer,db.ForeignKey("user_accounts.id"),nullable=False,index=True)
    filename=db.Column(db.String(255))
    created_count=db.Column(db.Integer,nullable=False,default=0)
    updated_count=db.Column(db.Integer,nullable=False,default=0)
    error_count=db.Column(db.Integer,nullable=False,default=0)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    account=db.relationship("UserAccount")

class Duty(db.Model):
    __tablename__="duties"
    id=db.Column(db.Integer,primary_key=True)
    code=db.Column(db.String(40),nullable=False,unique=True)
    name=db.Column(db.String(120),nullable=False)
    active=db.Column(db.Boolean,nullable=False,default=True)

class DutyAssignment(db.Model):
    __tablename__="duty_assignments"
    id=db.Column(db.Integer,primary_key=True)
    meeting_id=db.Column(db.Integer,db.ForeignKey("meetings.id"),nullable=False,index=True)
    duty_id=db.Column(db.Integer,db.ForeignKey("duties.id"),nullable=False,index=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    status=db.Column(db.String(30),nullable=False,default="DRAFT")
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class Notification(db.Model):
    __tablename__="notifications"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    type=db.Column(db.String(50),nullable=False)
    title=db.Column(db.String(255),nullable=False)
    message=db.Column(db.Text)
    link=db.Column(db.String(120))
    read_at=db.Column(db.DateTime)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class RequestRecipient(db.Model):
    __tablename__="request_recipients"
    id=db.Column(db.Integer,primary_key=True)
    request_type=db.Column(db.String(40),nullable=False,index=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class MemberRequest(db.Model):
    __tablename__="member_requests"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    type=db.Column(db.String(40),nullable=False,index=True)
    title=db.Column(db.String(255))
    message=db.Column(db.Text)
    guest_name=db.Column(db.String(255))
    guest_email=db.Column(db.String(255))
    event_date=db.Column(db.Date)
    event_time=db.Column(db.String(5))
    event_location=db.Column(db.String(255))
    attachment_name=db.Column(db.String(255))
    attachment_type=db.Column(db.String(120))
    attachment_data=db.Column(db.LargeBinary)
    status=db.Column(db.String(30),nullable=False,default="TO_PROCESS")
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class SwapRequest(db.Model):
    __tablename__="swap_requests"
    id=db.Column(db.Integer,primary_key=True)
    assignment_id=db.Column(db.Integer,db.ForeignKey("duty_assignments.id"),nullable=False,index=True)
    requester_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    volunteer_id=db.Column(db.Integer,db.ForeignKey("members.id"),index=True)
    status=db.Column(db.String(30),nullable=False,default="OPEN")
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class Referral(db.Model):
    __tablename__="referrals"
    id=db.Column(db.Integer,primary_key=True)
    from_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    to_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    contact_name=db.Column(db.String(180),nullable=False)
    company=db.Column(db.String(180))
    contact_email=db.Column(db.String(180))
    contact_phone=db.Column(db.String(60))
    notes=db.Column(db.Text)
    status=db.Column(db.String(30),nullable=False,default="SENT",index=True)
    estimated_value=db.Column(db.Numeric(12,2))
    closed_at=db.Column(db.DateTime,index=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)
    updated_at=db.Column(db.DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)

class ReferralStatusHistory(db.Model):
    __tablename__="referral_status_history"
    id=db.Column(db.Integer,primary_key=True)
    referral_id=db.Column(db.Integer,db.ForeignKey("referrals.id"),nullable=False,index=True)
    status=db.Column(db.String(30),nullable=False)
    note=db.Column(db.Text)
    changed_by_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class BusinessThanks(db.Model):
    __tablename__="business_thanks"
    id=db.Column(db.Integer,primary_key=True)
    from_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    credited_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    referral_id=db.Column(db.Integer,db.ForeignKey("referrals.id"),nullable=True,index=True)
    amount=db.Column(db.Numeric(12,2),nullable=False)
    notes=db.Column(db.Text)
    business_date=db.Column(db.Date,nullable=False,default=date.today,index=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class OneToOne(db.Model):
    __tablename__="one_to_ones"
    id=db.Column(db.Integer,primary_key=True)
    member_a_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    member_b_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    meeting_date=db.Column(db.Date,nullable=False,default=date.today,index=True)
    duration_minutes=db.Column(db.Integer)
    notes=db.Column(db.Text)
    created_by_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class NetworkVisitor(db.Model):
    __tablename__="network_visitors"
    id=db.Column(db.Integer,primary_key=True)
    invited_by_member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    name=db.Column(db.String(180),nullable=False)
    company=db.Column(db.String(180))
    activity=db.Column(db.String(180))
    email=db.Column(db.String(180))
    phone=db.Column(db.String(60))
    visit_date=db.Column(db.Date,nullable=False,default=date.today,index=True)
    status=db.Column(db.String(30),nullable=False,default="INVITED",index=True)
    notes=db.Column(db.Text)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False,index=True)

class Announcement(db.Model):
    __tablename__="announcements"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    start_date=db.Column(db.Date,nullable=False)
    end_date=db.Column(db.Date,nullable=False,index=True)
    subject=db.Column(db.String(180),nullable=False)
    description=db.Column(db.Text,nullable=False)
    active=db.Column(db.Boolean,nullable=False,default=True)
    created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)

class AnnouncementInterest(db.Model):
    __tablename__="announcement_interests"
    announcement_id=db.Column(db.Integer,db.ForeignKey("announcements.id"),primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),primary_key=True)
    active=db.Column(db.Boolean,nullable=False,default=False)

class GuestVisitReviewer(db.Model):
    __tablename__="guest_visit_reviewers"
    key=db.Column(db.String(20),primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,unique=True)

class AlumniGuestVisit(db.Model):
    __tablename__="alumni_guest_visits"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    mandate_id=db.Column(db.Integer,db.ForeignKey("mandates.id"),nullable=False,index=True)
    date=db.Column(db.Date,nullable=False,index=True)
    message=db.Column(db.Text)
    status=db.Column(db.String(20),nullable=False,default="PENDING")
    decision_reason=db.Column(db.String(500))
    decided_by=db.Column(db.Integer,db.ForeignKey("user_accounts.id"))
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class AttendanceRecord(db.Model):
    __tablename__="attendance_records"
    id=db.Column(db.Integer,primary_key=True)
    meeting_id=db.Column(db.Integer,db.ForeignKey("meetings.id"),nullable=False,index=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    status=db.Column(db.String(30),nullable=False,default="PRESENT",index=True)
    notes=db.Column(db.Text)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)
    __table_args__=(db.UniqueConstraint("meeting_id","member_id",name="uq_attendance_meeting_member"),)

class AlumniAvailability(db.Model):
    __tablename__="alumni_availability"
    id=db.Column(db.Integer,primary_key=True)
    member_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    date=db.Column(db.Date,nullable=False,index=True)
    note=db.Column(db.String(500))
    active=db.Column(db.Boolean,nullable=False,default=True)
    __table_args__=(db.UniqueConstraint("member_id","date"),)

class AlumniSubstitution(db.Model):
    __tablename__="alumni_substitutions"
    id=db.Column(db.Integer,primary_key=True)
    official_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    alumni_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    availability_id=db.Column(db.Integer,db.ForeignKey("alumni_availability.id"),nullable=False)
    date=db.Column(db.Date,nullable=False,index=True)
    status=db.Column(db.String(20),nullable=False,default="REQUESTED")
    created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)

class AlumniReplacementNeed(db.Model):
    __tablename__="alumni_replacement_needs"
    id=db.Column(db.Integer,primary_key=True)
    official_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=False,index=True)
    alumni_id=db.Column(db.Integer,db.ForeignKey("members.id"),nullable=True,index=True)
    date=db.Column(db.Date,nullable=False,index=True)
    note=db.Column(db.String(500))
    status=db.Column(db.String(20),nullable=False,default="OPEN")
    created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
    accepted_at=db.Column(db.DateTime)
    __table_args__=(db.UniqueConstraint("official_id","date",name="uq_replacement_need_official_date"),)

class Meeting(db.Model):
    __tablename__="meetings"
    id=db.Column(db.Integer,primary_key=True)
    date=db.Column(db.Date,nullable=False,index=True)
    start_time=db.Column(db.Time)
    type=db.Column(db.String(40),nullable=False,default="REGULAR")
    location=db.Column(db.String(180))
    status=db.Column(db.String(30),nullable=False,default="PLANNED")
    notes=db.Column(db.Text)

def create_app():
    app=Flask(__name__)
    database_url=os.getenv("DATABASE_URL","sqlite:///bni_dev.db")
    if database_url.startswith("postgres://"):
        database_url=database_url.replace("postgres://","postgresql://",1)
    app.config["SQLALCHEMY_DATABASE_URI"]=database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    db.init_app(app)
    CORS(app,origins=os.getenv("CORS_ORIGINS",HUB_APP_URL).split(","))

    @app.get("/api/public/website")
    def public_website():
        # Explicit public projection: never reuse the authenticated directory payload.
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        members=[]
        for member in Member.query.order_by(Member.last_name,Member.first_name).all():
            membership=active_membership_for(member.id)
            if not official_member(member):continue
            if membership.start_date and membership.start_date>today:continue
            if membership.end_date and membership.end_date<today:continue
            if member.user_account and member.user_account.status in {"DISABLED","SUSPENDED"}:continue
            members.append({"firstName":member.first_name,"lastName":member.last_name,"company":member.company or "","activity":member.activity or ""})
        unique={}
        for item in members:
            key=tuple(unicodedata.normalize("NFKC",item[k]).strip().casefold() for k in ("firstName","lastName","company"))
            if key not in unique:unique[key]=item
            elif item["activity"] and item["activity"] not in unique[key]["activity"]:
                unique[key]["activity"]=" · ".join(filter(None,[unique[key]["activity"],item["activity"]]))
        members=list(unique.values())
        meetings=[{"date":m.date.isoformat(),"startTime":m.start_time.strftime("%H:%M") if m.start_time else None,"type":m.type,"location":m.location or ""} for m in Meeting.query.filter(Meeting.date>=today,Meeting.date<=today+timedelta(days=180),Meeting.status!="CANCELLED",Meeting.type!="NO_MEETING").order_by(Meeting.date).limit(30).all()]
        response=jsonify({"members":members,"meetings":meetings,"updatedAt":today.isoformat()})
        response.headers["Cache-Control"]="public, max-age=300"
        origin=request.headers.get("Origin")
        if origin in {"https://www.bim-soignies.be","https://bim-soignies.be"}:
            response.headers["Access-Control-Allow-Origin"]=origin
            response.headers["Vary"]="Origin"
        return response

    visit_mail_limits={}
    visit_ip_limits={}
    from threading import Lock
    visit_mail_lock=Lock()

    @app.post("/api/public/vitralux-registration")
    @cross_origin(origins=["https://www.bim-soignies.be","https://bim-soignies.be"],methods=["POST","OPTIONS"])
    def vitralux_registration():
        import re, hashlib, time as clock
        if request.headers.get("Origin") not in {"https://www.bim-soignies.be","https://bim-soignies.be"}:
            return {"error":"Veuillez utiliser le formulaire du site BNI Soignies."},403
        if request.content_length and request.content_length>12000:return {"error":"Formulaire trop volumineux."},413
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return {"error":"Formulaire invalide."},400
        if data.get("website"):return {"error":"Formulaire invalide."},400
        if data.get("consent") is not True:return {"error":"Veuillez autoriser la transmission de votre demande au groupe."},400
        fields={key:str(data.get(key,"")).strip() for key in ["firstName","lastName","company","activity","email","phone","message"]}
        if any(len(value)>limit for key,value in fields.items() for limit in [1500 if key=="message" else 180]):return {"error":"Un champ dépasse la longueur autorisée."},400
        if any(not fields[key] for key in ["firstName","lastName","email"]):return {"error":"Indiquez vos prénom, nom et e-mail."},400
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+",fields["email"]) or any(c in fields["email"] for c in "\r\n"):
            return {"error":"Adresse e-mail invalide."},400
        if datetime.now(ZoneInfo("Europe/Brussels")).date()>date(2026,11,19):return {"error":"Les inscriptions pour cette rencontre sont clôturées."},410
        # Bounded, short-lived anti-repeat guard; recipient is fixed server-side.
        key=hashlib.sha256((fields["email"].casefold()+"|"+(request.remote_addr or "")).encode()).hexdigest()
        now=clock.monotonic()
        ip_key=hashlib.sha256((request.remote_addr or "unknown").encode()).hexdigest()
        with visit_mail_lock:
            for old in list(visit_ip_limits):
                visit_ip_limits[old]=[stamp for stamp in visit_ip_limits[old] if now-stamp<600]
                if not visit_ip_limits[old]:visit_ip_limits.pop(old,None)
            if len(visit_ip_limits.get(ip_key,[]))>=5:return {"error":"Trop de demandes rapprochées. Réessayez dans quelques minutes."},429
            visit_ip_limits.setdefault(ip_key,[]).append(now)
            for old in list(visit_mail_limits):
                if now-visit_mail_limits[old]>600:visit_mail_limits.pop(old,None)
            if key in visit_mail_limits and now-visit_mail_limits[key]<60:return {"error":"Une demande vient déjà d’être envoyée. Patientez une minute avant de réessayer."},429
            if len(visit_mail_limits)>2000:return {"error":"Le service est temporairement occupé. Réessayez dans quelques minutes."},503
            visit_mail_limits[key]=now
        body="Demande d’inscription — Petit déjeuner BNI chez Vitralux\n19 novembre 2026, de 7h à 9h\nRue Grande 4, 7020 Maisières\n\n"+"\n".join(label+": "+(fields[field] or "Non renseigné") for field,label in [("firstName","Prénom"),("lastName","Nom"),("company","Entreprise"),("activity","Activité"),("email","E-mail"),("phone","Téléphone"),("message","Message")])+"\n\nLe visiteur a autorisé la transmission de sa demande à hub@bim-soignies.be.\nMerci de lui confirmer les modalités de sa visite."
        try:sent=send_simple_email("hub@bim-soignies.be","Inscription Vitralux — 19/11/2026",body)
        except Exception:
            app.logger.warning("Vitralux registration mail unavailable")
            sent=False
        if not sent:
            with visit_mail_lock:visit_mail_limits.pop(key,None)
            return {"error":"L’envoi n’a pas abouti. Réessayez ou contactez hub@bim-soignies.be. Votre inscription n’est pas confirmée."},503
        return {"status":"sent","message":"Votre demande a été envoyée à BNI Soignies BIM. Le groupe vous confirmera votre visite."},201

    @app.get("/health")
    def health():
        return {"status":"ok","service":"bni-soignies-api"}

    @app.get("/api")
    def api():
        return {"name":"HUB Soignies API","version":"0.1.0"}

    def audit(account,action,entity_type=None,entity_id=None,details=None):
        try:
            db.session.add(AuditLog(account_id=account.id if account else None,member_id=account.member_id if account else None,action=action,entity_type=entity_type,entity_id=str(entity_id) if entity_id is not None else None,details=details))
        except Exception:
            pass

    def active_mandate(on_date=None):
        d=on_date or datetime.now(ZoneInfo("Europe/Brussels")).date()
        return Mandate.query.filter(Mandate.start_date<=d,Mandate.end_date>=d).order_by(Mandate.start_date.desc()).first()

    def current_assignment(member_id,role_id=None,on_date=None):
        mandate=active_mandate(on_date)
        if not mandate:return None
        q=RoleAssignment.query.filter_by(member_id=member_id,mandate_id=mandate.id,status="ACTIVE")
        if role_id is not None:q=q.filter_by(role_id=role_id)
        return q.first()

    def require_admin():
        account,session=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if session.support_actor_id:return None,({"error":"Administration inaccessible en mode assistance."},403)
        if not account_payload(account)["isAdmin"]:return None,({"error":"Accès administrateur requis."},403)
        return account,None

    def require_system_admin():
        account,session=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if session.support_actor_id:return None,({"error":"Administration inaccessible en mode assistance."},403)
        if not account.is_system_admin:return None,({"error":"Accès administrateur système requis."},403)
        return account,None

    def feature_enabled(key):
        row=db.session.get(FeatureFlag,key)
        return bool(row and row.enabled)

    def active_membership_for(member_id):
        return Membership.query.filter_by(member_id=member_id).order_by(Membership.id.desc()).first()

    def has_off_members():
        return db.session.query(Member.id).join(Membership,Membership.member_id==Member.id).filter(
            Membership.status.in_(["ACTIVE","ONBOARDING","OFF"]),
            Member.network_type=="OFF"
        ).first() is not None

    def official_member(member):
        membership=active_membership_for(member.id)
        return bool(membership and membership.status in {"ACTIVE","ONBOARDING"} and member.network_type!="OFF")

    def alumni_member(member):
        membership=active_membership_for(member.id)
        return bool(membership and membership.status in {"ACTIVE","ONBOARDING","OFF"} and (membership.status=="OFF" or member.network_type=="OFF"))

    def network_bridge_enabled(account):
        return bool(official_member(account.member) and account.member.alumni_bridge_enabled)

    def full_network_enabled(account):
        return bool(alumni_member(account.member) or network_bridge_enabled(account))

    def require_feature(key):
        account,_=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if key in {"REFERRALS","BUSINESS","ONE_TO_ONE","ACTIVITY_SCORE"}:
            if full_network_enabled(account):return account,None
            return None,({"error":"La liaison avec les anciens est désactivée. Vous pouvez l'activer personnellement dans Profil."},403)
        if key=="VISITORS":
            if official_member(account.member):return account,None
            return None,({"error":"Les invitations aux réunions relèvent de l'espace Membres."},403)
        if account.is_system_admin:return account,None
        if feature_enabled("NETWORK_MODULE") and feature_enabled(key) and full_network_enabled(account):return account,None
        return None,({"error":"Fonctionnalité non disponible dans cet espace."},403)

    @app.before_request
    def enforce_environment():
        if not request.path.startswith("/api/"):return None
        account,session=bearer_account()
        if session and session.support_actor_id:
            if request.path.startswith(("/api/network/contributors","/api/network/hub-summary","/api/network/leaderboard")):return {"error":"Statistiques administratives inaccessibles en mode assistance."},403
            if request.path.startswith("/api/system/") and request.path!="/api/system/support-sessions/stop":return {"error":"Administration inaccessible en mode assistance."},403
            if request.method not in {"GET","HEAD","OPTIONS"} and request.path!="/api/system/support-sessions/stop":return {"error":"Mode assistance en lecture seule. Revenez à votre compte administrateur pour agir."},403
        if not account or account.is_system_admin:return None
        path=request.path
        if path.startswith(("/api/network/contributors","/api/network/hub-summary","/api/network/leaderboard")):
            if not account_payload(account)["isAdmin"]:return {"error":"Statistiques collectives réservées au comité."},403
        official_paths=("/api/meetings","/api/planning","/api/duties","/api/duty-assignments","/api/swaps","/api/me/duty-assignments","/api/documents","/api/resources","/api/platforms","/api/vault","/api/handovers","/api/me/handovers","/api/onboarding","/api/mandates","/api/roles","/api/request-recipients","/api/me/request-inbox")
        event_submission=False
        if path=="/api/me/requests" and request.method=="POST":
            data=request.form if request.content_type and request.content_type.startswith("multipart/form-data") else (request.get_json(silent=True) or {})
            event_submission=alumni_member(account.member) and str(data.get("type","")).strip().upper()=="EVENT"
        protected=path.startswith(official_paths) or (path.startswith("/api/member-requests") and not path.endswith("/attachment")) or (path=="/api/me/requests" and request.method!="GET" and not event_submission)
        if protected and not official_member(account.member):return {"error":"Cette fonction appartient à l'espace Membres. Les anciens accèdent aux réunions uniquement sur sollicitation de suppléance."},403

    def personal_activity_period(member_id):
        member=db.session.get(Member,member_id)
        if not alumni_member(member):return active_mandate()
        from types import SimpleNamespace
        history=MemberNetworkHistory.query.filter_by(member_id=member_id,network_type="OFF").order_by(MemberNetworkHistory.start_date.desc()).first()
        membership=active_membership_for(member_id)
        today=date.today()
        start=history.start_date if history else (membership.start_date or today)
        return SimpleNamespace(id=None,name="Espace Anciens",start_date=start,end_date=today)

    @app.get("/api/alumni-space/me")
    def alumni_space_me():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        member=account.member
        environment="ALUMNI" if alumni_member(member) else "MEMBERS" if official_member(member) else "INACTIVE"
        return {"environment":environment,"bridgeEnabled":bool(official_member(member) and member.alumni_bridge_enabled),"requestedAt":member.alumni_requested_at.isoformat() if member.alumni_requested_at else None,"stats":member_statistics(member.id,personal_activity_period(member.id)) if alumni_member(member) else None}

    @app.put("/api/me/alumni-bridge")
    def my_alumni_bridge():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not official_member(account.member):return {"error":"La liaison est un choix personnel des membres actifs."},403
        enabled=(request.get_json(silent=True) or {}).get("enabled")
        if not isinstance(enabled,bool):return {"error":"Choisissez activer ou désactiver."},400
        account.member.alumni_bridge_enabled=enabled
        audit(account,"ALUMNI_BRIDGE_CHANGED","member",account.member_id,f"enabled={enabled}")
        db.session.commit()
        return {"member":account_payload(account),"bridgeEnabled":enabled}

    @app.post("/api/me/alumni-request")
    def request_alumni_transition():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if alumni_member(account.member):return {"error":"Votre espace Anciens est déjà actif."},400
        if not account.member.alumni_requested_at:
            account.member.alumni_requested_at=datetime.utcnow()
            for admin in UserAccount.query.filter_by(is_system_admin=True,status="ACTIVE").all():
                notify(admin.member_id,"ALUMNI_REQUEST","Demande d'accès Anciens",member_name(account.member_id)+" demande son passage dans l'espace Anciens.","members")
            audit(account,"ALUMNI_TRANSITION_REQUESTED","member",account.member_id)
            db.session.commit()
        return {"requested":True,"message":"Votre demande est enregistrée. L'administrateur validera le passage après votre départ."}

    def release_future_welcome(member_id,today):
        for assignment in DutyAssignment.query.join(Meeting,Meeting.id==DutyAssignment.meeting_id).filter(DutyAssignment.member_id==member_id,Meeting.date>=today,DutyAssignment.status.in_(["DRAFT","PUBLISHED"])).all():
            assignment.status="TO_REASSIGN"
            if not SwapRequest.query.filter_by(assignment_id=assignment.id,status="OPEN").first():db.session.add(SwapRequest(assignment_id=assignment.id,requester_id=member_id,status="OPEN"))

    @app.post("/api/members/<int:member_id>/alumni-activate")
    def activate_alumni_transition(member_id):
        account,err=require_system_admin()
        if err:return err
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        if not member.alumni_requested_at:return {"error":"Une demande personnelle du membre est nécessaire."},400
        if alumni_member(member):return member_payload(member)
        today=date.today();previous=active_membership_for(member_id)
        if previous:previous.status="FORMER";previous.end_date=today-timedelta(days=1)
        db.session.add(Membership(member_id=member_id,status="OFF",start_date=today))
        current=MemberNetworkHistory.query.filter_by(member_id=member_id,end_date=None).first()
        if current:current.end_date=today-timedelta(days=1)
        db.session.add(MemberNetworkHistory(member_id=member_id,network_type="OFF",start_date=today,changed_by_account_id=account.id))
        member.network_type="OFF";member.network_access_enabled=True;member.alumni_bridge_enabled=False
        release_future_welcome(member_id,today)
        notify(member_id,"ALUMNI_ACTIVATED","Bienvenue dans l'espace Anciens","Votre historique est conservé. Votre accès à l'espace Membres est fermé.","home")
        audit(account,"ALUMNI_TRANSITION_ACTIVATED","member",member_id)
        db.session.commit()
        return member_payload(member)

    def availability_payload(x):
        member=db.session.get(Member,x.member_id)
        return {"id":x.id,"memberId":x.member_id,"member":member_name(x.member_id),"company":member.company,"date":x.date.isoformat(),"note":x.note,"active":x.active}

    def replacement_account():
        # Replacement access is independent of the optional business bridge.
        account,_=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if not (official_member(account.member) or alumni_member(account.member)):
            return None,({"error":"Réservé aux membres et anciens actifs."},403)
        return account,None

    def visible_alumni_availability():
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        rows=AlumniAvailability.query.filter(AlumniAvailability.date>=today,AlumniAvailability.active==True).order_by(AlumniAvailability.date,AlumniAvailability.id).all()
        available=[]
        for offer in rows:
            member=db.session.get(Member,offer.member_id)
            if not member or not alumni_member(member) or not member.user_account or member.user_account.status!="ACTIVE":continue
            if AlumniGuestVisit.query.filter_by(member_id=member.id,date=offer.date,status="APPROVED").first():continue
            if AlumniSubstitution.query.filter_by(alumni_id=member.id,date=offer.date,status="ACCEPTED").first():continue
            if AlumniReplacementNeed.query.filter_by(alumni_id=member.id,date=offer.date,status="ACCEPTED").first():continue
            available.append(offer)
        return available

    def announcement_account():
        account,_=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if not (official_member(account.member) or alumni_member(account.member)):return None,({"error":"Réservé aux membres et anciens actifs."},403)
        return account,None

    def announcement_payload(x,account):
        interest=AnnouncementInterest.query.filter_by(announcement_id=x.id,member_id=account.member_id).first()
        return {"id":x.id,"memberId":x.member_id,"member":member_name(x.member_id),"startDate":x.start_date.isoformat(),"endDate":x.end_date.isoformat(),"subject":x.subject,"description":x.description,"createdAt":x.created_at.isoformat()+"Z","interested":bool(interest and interest.active),"interestCount":AnnouncementInterest.query.filter_by(announcement_id=x.id,active=True).count(),"own":x.member_id==account.member_id}

    @app.route("/api/announcements",methods=["GET","POST"])
    def announcements():
        account,err=announcement_account()
        if err:return err
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        if request.method=="GET":
            rows=Announcement.query.filter(db.or_(Announcement.start_date<=today,Announcement.member_id==account.member_id),Announcement.end_date>today,Announcement.active==True).order_by(Announcement.created_at.desc(),Announcement.id.desc()).all()
            return jsonify([announcement_payload(x,account) for x in rows])
        data=request.get_json(silent=True) or {}
        try:
            start=date.fromisoformat(str(data.get("date","")));days=int(data.get("durationDays",31))
            if start<today or days<1 or days>31:raise ValueError()
        except (ValueError,TypeError,OverflowError):return {"error":"Choisissez une date à venir et une durée comprise entre 1 et 31 jours."},400
        subject=str(data.get("subject") or "").strip();description=str(data.get("description") or "").strip()
        if not subject or len(subject)>180 or not description or len(description)>4000:return {"error":"Sujet (180 caractères max.) et descriptif (4000 caractères max.) obligatoires."},400
        x=Announcement(member_id=account.member_id,start_date=start,end_date=start+timedelta(days=days),subject=subject,description=description)
        db.session.add(x);db.session.flush();audit(account,"ANNOUNCEMENT_CREATED","announcement",x.id);db.session.commit()
        return announcement_payload(x,account),201

    @app.put("/api/announcements/<int:item_id>/interest")
    def announcement_interest(item_id):
        account,err=announcement_account()
        if err:return err
        # Serialize toggles, including first clicks, to prevent duplicate rows/notices.
        x=Announcement.query.filter_by(id=item_id).with_for_update().first()
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        if not x or not x.active or not (x.start_date<=today<x.end_date):return {"error":"Cette annonce n’est plus disponible."},404
        if x.member_id==account.member_id:return {"error":"Vous êtes l’auteur de cette annonce."},403
        data=request.get_json(silent=True) or {}
        if type(data.get("interested")) is not bool:return {"error":"Choix invalide."},400
        interested=data["interested"]
        row=AnnouncementInterest.query.filter_by(announcement_id=x.id,member_id=account.member_id).first()
        was_active=bool(row and row.active)
        if not row:row=AnnouncementInterest(announcement_id=x.id,member_id=account.member_id);db.session.add(row)
        row.active=interested
        if interested and not was_active:notify(x.member_id,"ANNOUNCEMENT_INTEREST",member_name(account.member_id)+" est intéressé par votre annonce",x.subject,"announcements")
        db.session.commit();return announcement_payload(x,account)

    @app.delete("/api/announcements/<int:item_id>")
    def withdraw_announcement(item_id):
        account,err=announcement_account()
        if err:return err
        x=db.session.get(Announcement,item_id)
        if not x:return {"error":"Annonce introuvable."},404
        if x.member_id!=account.member_id:return {"error":"Cette annonce appartient à un autre membre."},403
        x.active=False;audit(account,"ANNOUNCEMENT_WITHDRAWN","announcement",x.id);db.session.commit();return {"status":"WITHDRAWN"}

    def guest_reviewers():
        members=[db.session.get(Member,row.member_id) for row in GuestVisitReviewer.query.all()]
        return [m for m in members if m and official_member(m)]

    def can_review_guest(account):
        return bool(account.is_system_admin or (official_member(account.member) and GuestVisitReviewer.query.filter(GuestVisitReviewer.member_id==account.member_id,GuestVisitReviewer.key.in_(["amelie","simon"])).first()))

    def guest_visit_payload(x):
        return {"id":x.id,"member":member_name(x.member_id),"memberId":x.member_id,"date":x.date.isoformat(),"message":x.message,"status":x.status,"decisionReason":x.decision_reason,"mandateId":x.mandate_id}

    def guest_visit_mail(member,subject,body):
        try:return send_simple_email(member.user_account.email if member.user_account and member.user_account.status=="ACTIVE" else member.email,"HUB — "+subject,"Bonjour "+member.first_name+",\n\n"+body)
        except Exception:app.logger.exception("Guest visit email failed member_id=%s",member.id);return False

    @app.route("/api/alumni-visits",methods=["GET","POST"])
    def alumni_guest_visits():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not alumni_member(account.member):return {"error":"Réservé aux anciens membres."},403
        if request.method=="GET":
            rows=AlumniGuestVisit.query.filter_by(member_id=account.member_id).order_by(AlumniGuestVisit.date.desc(),AlumniGuestVisit.id.desc()).all()
            meetings=Meeting.query.filter(Meeting.date>=datetime.now(ZoneInfo("Europe/Brussels")).date(),Meeting.type!="NO_MEETING",Meeting.status!="CANCELLED").order_by(Meeting.date).all()
            return {"items":[guest_visit_payload(x) for x in rows],"meetings":[{"date":m.date.isoformat(),"startTime":m.start_time.strftime("%H:%M") if m.start_time else None} for m in meetings if future_replacement_meeting(m.date)],"limit":2}
        data=request.get_json(silent=True) or {}
        try:day=date.fromisoformat(data.get("date",""))
        except (ValueError,TypeError):return {"error":"Date invalide."},400
        lock_replacement_members(account.member_id)
        if not future_replacement_meeting(day):return {"error":"Choisissez une réunion à venir programmée."},400
        mandate=active_mandate(day)
        if not mandate:return {"error":"Aucune mandature configurée pour cette date."},400
        existing=AlumniGuestVisit.query.filter(AlumniGuestVisit.member_id==account.member_id,AlumniGuestVisit.date==day,AlumniGuestVisit.status.in_(["PENDING","APPROVED"])).first()
        if existing:return guest_visit_payload(existing),200
        if AlumniGuestVisit.query.filter_by(member_id=account.member_id,mandate_id=mandate.id).count()>=2:return {"error":"Vous avez déjà utilisé vos deux demandes d’invitation pour cette mandature."},409
        if replacement_conflict(day,-1,account.member_id):return {"error":"Une suppléance est déjà confirmée pour vous à cette date. Contactez le comité pour modifier cet engagement."},409
        availability_id=data.get("availabilityId")
        if availability_id:
            offer=AlumniAvailability.query.filter_by(id=availability_id,member_id=account.member_id).with_for_update().first()
            if not offer or offer.date!=day or not offer.active:return {"error":"Disponibilité introuvable ou retirée."},400
            offer.active=False
        for row in AlumniSubstitution.query.filter_by(alumni_id=account.member_id,date=day,status="REQUESTED").all():
            row.status="CANCELLED"
            notify(row.official_id,"SUBSTITUTION_CANCELLED","Proposition de suppléance retirée",member_name(account.member_id)+" souhaite venir comme invité le "+day.isoformat()+". Sa suppléance n’est plus proposée.","substitutions")
        x=AlumniGuestVisit(member_id=account.member_id,date=day,mandate_id=mandate.id,message=str(data.get("message") or "")[:2000],status="PENDING")
        db.session.add(x);db.session.flush()
        reviewers=guest_reviewers()
        for member in reviewers:notify(member.id,"ALUMNI_GUEST_REQUEST","Demande de venue comme invité",member_name(account.member_id)+" demande à venir le "+day.strftime("%d/%m/%Y"),"guestVisits")
        audit(account,"ALUMNI_GUEST_REQUESTED","alumni_guest_visit",x.id);db.session.commit()
        for member in reviewers:guest_visit_mail(member,"Demande d’invitation d’un ancien",f"L’ancien membre {member_name(account.member_id)} a demandé à venir en tant qu’invité le {day.strftime('%d/%m/%Y')}.\n\nProjet : {x.message or 'Non précisé'}\n\nValide via HUB APP son inscription :\n{HUB_APP_URL}/?guestVisits=1\n")
        return guest_visit_payload(x),201

    @app.delete("/api/alumni-visits/<int:visit_id>")
    def withdraw_guest_visit(visit_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        lock_replacement_members(account.member_id)
        x=AlumniGuestVisit.query.filter_by(id=visit_id,member_id=account.member_id).with_for_update().first()
        if not x:return {"error":"Demande introuvable."},404
        if x.status!="PENDING":return {"error":"Seule une demande en attente peut être retirée. Contactez le comité pour une inscription confirmée."},409
        x.status="WITHDRAWN";audit(account,"ALUMNI_GUEST_WITHDRAWN","alumni_guest_visit",x.id);db.session.commit()
        return guest_visit_payload(x)

    @app.route("/api/alumni-visits/review",methods=["GET"])
    def review_guest_visit_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not can_review_guest(account):return {"error":"Validation réservée à Amélie, Simon et au super admin."},403
        return jsonify([guest_visit_payload(x) for x in AlumniGuestVisit.query.order_by(AlumniGuestVisit.created_at.desc()).all()])

    @app.patch("/api/alumni-visits/<int:visit_id>/decision")
    def decide_guest_visit(visit_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not can_review_guest(account):return {"error":"Validation non autorisée."},403
        x=db.session.get(AlumniGuestVisit,visit_id)
        if not x:return {"error":"Demande introuvable."},404
        lock_replacement_members(x.member_id)
        x=AlumniGuestVisit.query.filter_by(id=visit_id).with_for_update().populate_existing().first()
        if x.status!="PENDING":return {"error":"Cette demande a déjà été traitée."},409
        data=request.get_json(silent=True) or {};status=data.get("status")
        if status not in {"APPROVED","DECLINED"}:return {"error":"Décision invalide."},400
        if status=="APPROVED":
            if not future_replacement_meeting(x.date):return {"error":"Cette réunion a été annulée ou n’est plus à venir."},409
            if replacement_conflict(x.date,-1,x.member_id):return {"error":"Cet ancien assure déjà une suppléance ou a une invitation confirmée à cette date."},409
            member=db.session.get(Member,x.member_id)
            db.session.add(NetworkVisitor(invited_by_member_id=member.id,name=member_name(member.id),company=member.company,visit_date=x.date,status="INVITED",notes="Ancien invité · demande #"+str(x.id)))
            for offer in AlumniAvailability.query.filter_by(member_id=x.member_id,date=x.date).all():offer.active=False
        x.status=status;x.decision_reason=str(data.get("reason") or "")[:500];x.decided_by=account.id
        word="acceptée" if status=="APPROVED" else "refusée"
        notify(x.member_id,"ALUMNI_GUEST_DECISION","Demande d’invitation "+word,"Ta demande d’invitation du "+x.date.strftime("%d/%m/%Y")+" a été "+word+".","guestVisits")
        audit(account,"ALUMNI_GUEST_DECIDED","alumni_guest_visit",x.id,status);db.session.commit()
        guest_visit_mail(db.session.get(Member,x.member_id),"Ta demande d’invitation a été "+word,"Ta demande d’invitation pour le "+x.date.strftime("%d/%m/%Y")+" a été "+word+".\n"+(x.decision_reason or "")+"\n\nConsulter le HUB :\n"+HUB_APP_URL+"/?guestVisits=1\n")
        return guest_visit_payload(x)

    def lock_replacement_members(*ids):
        # Shared locks across open calls and targeted requests; stable order avoids deadlocks.
        return Member.query.filter(Member.id.in_(ids)).order_by(Member.id).with_for_update().populate_existing().all()

    def future_replacement_meeting(day):
        now=datetime.now(ZoneInfo("Europe/Brussels"))
        if day<now.date():return None
        rows=Meeting.query.filter_by(date=day).filter(Meeting.type!="NO_MEETING",Meeting.status!="CANCELLED").order_by(Meeting.start_time).all()
        return next((m for m in rows if day>now.date() or not m.start_time or m.start_time>now.time().replace(tzinfo=None)),None)

    def replacement_conflict(day,official_id,alumni_id=None,exclude_target=None,exclude_need=None):
        if alumni_id and AlumniGuestVisit.query.filter_by(member_id=alumni_id,date=day,status="APPROVED").first():return True
        targeted=AlumniSubstitution.query.filter_by(date=day,status="ACCEPTED")
        needs=AlumniReplacementNeed.query.filter_by(date=day,status="ACCEPTED")
        if exclude_target:targeted=targeted.filter(AlumniSubstitution.id!=exclude_target)
        if exclude_need:needs=needs.filter(AlumniReplacementNeed.id!=exclude_need)
        targeted=targeted.filter(db.or_(AlumniSubstitution.official_id==official_id,AlumniSubstitution.alumni_id==alumni_id)) if alumni_id else targeted.filter_by(official_id=official_id)
        needs=needs.filter(db.or_(AlumniReplacementNeed.official_id==official_id,AlumniReplacementNeed.alumni_id==alumni_id)) if alumni_id else needs.filter_by(official_id=official_id)
        return targeted.first() is not None or needs.first() is not None

    def replacement_mail(member_id,title,message):
        try:
            member=db.session.get(Member,member_id)
            email=member.user_account.email if member.user_account else member.email
            base=HUB_APP_URL
            return send_simple_email(email,"HUB — "+title,f"Bonjour {member.first_name},\n\n{message}\n\nOuvre ton app pour consulter la suppléance :\n{base}/?substitutions=1\n")
        except Exception:
            app.logger.exception("Substitution email delivery failed")
            return False

    def welcome_replacement_emails(official_id,alumni_id,day,actor,entity,entity_id):
        # Exact identities resolved from the group's roster, never first-name guesses.
        identities=[("Amélie","Loedt"),("Simon","Vanwymeersch")]
        def normalized(value):
            return " ".join(unicodedata.normalize("NFKD",value or "").encode("ascii","ignore").decode().casefold().split())
        members=[m for m in Member.query.all() if official_member(m)]
        meeting=Meeting.query.filter_by(date=day).first()
        message=f"{member_name(alumni_id)} a accepté de remplacer {member_name(official_id)} le {day.strftime('%d/%m/%Y')}."
        details=("Heure : "+meeting.start_time.strftime("%H:%M")+"\n" if meeting and meeting.start_time else "")+("Lieu : "+meeting.location+"\n" if meeting and meeting.location else "")
        sent=0;skipped=0;seen=set()
        for first,last in identities:
            matches=[m for m in members if normalized(m.first_name)==normalized(first) and normalized(m.last_name)==normalized(last)]
            recipient=matches[0] if len(matches)==1 else None
            outcome="MEMBER_MISSING" if not matches else "AMBIGUOUS_MEMBER"
            if recipient:
                email=(recipient.user_account.email if recipient.user_account and recipient.user_account.status=="ACTIVE" else recipient.email) or ""
                if recipient.id==official_id:outcome="ALREADY_NOTIFIED_AS_REPLACED_MEMBER"
                elif not email.strip():outcome="EMAIL_MISSING"
                elif email.strip().lower() in seen:outcome="DUPLICATE_ADDRESS"
                else:
                    seen.add(email.strip().lower())
                    try:
                        accepted=send_simple_email(email,"HUB — Suppléance confirmée · comité d’accueil",f"Bonjour {recipient.first_name},\n\n{message}\n\n{details}\nLe comité d’accueil peut prévoir la présence du suppléant.\nConsulter le planning :\n{HUB_APP_URL}/?agenda={day.strftime('%Y-%m')}\n")
                        outcome="SMTP_ACCEPTED" if accepted else "MAIL_NOT_CONFIGURED"
                        if accepted:sent+=1
                    except Exception:
                        outcome="SEND_FAILED"
                        app.logger.exception("Welcome committee substitution email failed member_id=%s",recipient.id)
            if outcome!="SMTP_ACCEPTED":skipped+=1
            audit(actor,"WELCOME_SUBSTITUTION_EMAIL",entity,entity_id,f"recipient={first} {last};member_id={recipient.id if recipient else ''};outcome={outcome}")
            if outcome in {"MEMBER_MISSING","AMBIGUOUS_MEMBER","EMAIL_MISSING","MAIL_NOT_CONFIGURED","SEND_FAILED"}:app.logger.warning("Welcome substitution email not sent recipient=%s %s outcome=%s",first,last,outcome)
        db.session.commit()
        return {"sentCount":sent,"skippedCount":skipped}

    def replacement_notices(x,confirmed):
        message=(f"{member_name(x.alumni_id)} a accepté de remplacer {member_name(x.official_id)} le {x.date.isoformat()}." if confirmed else
            f"{member_name(x.official_id)} a sélectionné la disponibilité de {member_name(x.alumni_id)} pour le {x.date.isoformat()}. En attente de confirmation par l’ancien membre dans le HUB.")
        recipients={x.official_id,x.alumni_id}
        if confirmed:recipients.update(m.id for m in guest_reviewers())
        for mid in recipients:
            notify(mid,"SUBSTITUTION_ACCEPTED" if confirmed else "SUBSTITUTION_REQUEST","Suppléance confirmée" if confirmed else "Suppléance à confirmer",message,"substitutions")
        return message,len(recipients)

    def replacement_confirmation_emails(x,actor,entity,message):
        return {"emailSent":replacement_mail(x.official_id,"Suppléance confirmée",message),
            "alumniEmailSent":replacement_mail(x.alumni_id,"Votre engagement de suppléance est confirmé",message),
            "welcomeCommitteeEmails":welcome_replacement_emails(x.official_id,x.alumni_id,x.date,actor,entity,x.id)}

    def repair_replacement_notifications():
        # Explicit one-off resend requested by the administrator. Persist notices and
        # the unique run marker in one transaction before sending any mail.
        key="suppl-notices-20261110-v1"
        if db.engine.dialect.name=="postgresql":db.session.execute(text("SELECT pg_advisory_xact_lock(20261110, 731)"))
        existing=db.session.get(NotificationRepairRun,key)
        if existing:
            result=json.loads(existing.report);db.session.commit()
            app.logger.warning("HUB_SUPPLEANCE_REPORT %s",json.dumps(result,ensure_ascii=False));return result
        report={"confirmed":0,"requested":0,"notifications":0,"smtpAccepted":0,"mailAttempts":0,"jfLaurent":[]}
        def norm(value):return ''.join(c for c in unicodedata.normalize('NFKD',value or '').casefold() if c.isalnum() and not unicodedata.combining(c))
        jobs=[];seen=set()
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        for model,entity in [(AlumniSubstitution,"substitution"),(AlumniReplacementNeed,"replacement_need")]:
            rows=model.query.filter(model.date>=today,model.status.in_(["REQUESTED","ACCEPTED"])).order_by(model.date,model.id).all()
            for row in rows:
                if not row.alumni_id or not future_replacement_meeting(row.date):continue
                official=db.session.get(Member,row.official_id);alumni=db.session.get(Member,row.alumni_id)
                if not official or not alumni:continue
                if norm(official.first_name)=='laurent' and norm(official.last_name)=='sluys' and norm(alumni.first_name)=='jeanfrancois' and norm(alumni.last_name)=='crohin':
                    report['jfLaurent'].append({"date":row.date.isoformat(),"status":row.status,"source":entity,"id":row.id})
                identity=(row.date,row.official_id,row.alumni_id,row.status)
                if identity in seen:continue
                seen.add(identity)
                confirmed=row.status=='ACCEPTED'
                message,count=replacement_notices(row,confirmed)
                report['confirmed' if confirmed else 'requested']+=1;report['notifications']+=count
                jobs.append((row,entity,message,confirmed))
                audit(None,"REPLACEMENT_NOTIFICATIONS_REPLAYED",entity,row.id,row.status)
        db.session.add(NotificationRepairRun(key=key,report=json.dumps(report)));db.session.commit()
        app.logger.warning("HUB_SUPPLEANCE_NOTICES_PERSISTED %s",json.dumps(report,ensure_ascii=False))
        for row,entity,message,confirmed in jobs:
            report['mailAttempts']+=2
            report['smtpAccepted']+=int(bool(replacement_mail(row.official_id,'Suppléance confirmée' if confirmed else 'Suppléance à confirmer',message)))
            report['smtpAccepted']+=int(bool(replacement_mail(row.alumni_id,'Votre suppléance est confirmée' if confirmed else 'Merci de confirmer votre suppléance',message)))
            if confirmed:
                result=welcome_replacement_emails(row.official_id,row.alumni_id,row.date,None,entity,row.id)
                report['smtpAccepted']+=result['sentCount'];report['committeeSkipped']=report.get('committeeSkipped',0)+result['skippedCount']
        db.session.get(NotificationRepairRun,key).report=json.dumps(report);db.session.commit()
        app.logger.warning("HUB_SUPPLEANCE_REPORT %s",json.dumps(report,ensure_ascii=False))
        return report

    app.extensions['repair_replacement_notifications']=repair_replacement_notifications

    def replacement_need_payload(x,viewer_id):
        meeting=future_replacement_meeting(x.date)
        participant=viewer_id in {x.official_id,x.alumni_id}
        return {"id":x.id,"officialId":x.official_id,"official":member_name(x.official_id),"alumniId":x.alumni_id,"alumni":member_name(x.alumni_id) if x.alumni_id else None,"date":x.date.isoformat(),"note":x.note,"status":x.status,"acceptedAt":x.accepted_at.isoformat() if x.accepted_at else None,"location":meeting.location if meeting and participant else None,"startTime":meeting.start_time.strftime("%H:%M") if meeting and participant and meeting.start_time else None}

    @app.route("/api/alumni-space/replacement-needs",methods=["GET","POST"])
    def replacement_needs():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        is_alumni=alumni_member(account.member)
        if not is_alumni and not official_member(account.member):return {"error":"Réservé aux membres et anciens actifs."},403
        if request.method=="GET":
            rows=AlumniReplacementNeed.query.order_by(AlumniReplacementNeed.date.desc(),AlumniReplacementNeed.id.desc()).all()
            if is_alumni:
                rows=[x for x in rows if x.alumni_id==account.member_id or (x.date>=datetime.now(ZoneInfo("Europe/Brussels")).date() and official_member(db.session.get(Member,x.official_id)) and (x.status!="OPEN" or future_replacement_meeting(x.date)))]
            else:rows=[x for x in rows if x.official_id==account.member_id]
            return jsonify([replacement_need_payload(x,account.member_id) for x in rows])
        if is_alumni:return {"error":"Seul un membre actif peut publier un besoin."},403
        data=request.get_json(silent=True) or {}
        try:day=date.fromisoformat(data.get("date",""))
        except (ValueError,TypeError):return {"error":"Date invalide."},400
        lock_replacement_members(account.member_id)
        if not official_member(account.member):return {"error":"Réservé aux membres actifs."},403
        if not future_replacement_meeting(day):return {"error":"Choisissez une réunion à venir programmée dans le planning."},400
        if replacement_conflict(day,account.member_id):return {"error":"Votre remplacement est déjà assuré à cette date."},409
        x=AlumniReplacementNeed.query.filter_by(official_id=account.member_id,date=day).with_for_update().first()
        if x and x.status!="CANCELLED":return {"error":"Un besoin existe déjà pour cette date."},409
        if not x:x=AlumniReplacementNeed(official_id=account.member_id,date=day);db.session.add(x)
        x.status="OPEN";x.note=str(data.get("note") or "")[:500];x.alumni_id=None;x.accepted_at=None
        targets=[m.id for m in Member.query.all() if alumni_member(m) and m.user_account and m.user_account.status=="ACTIVE"]
        message=f"{member_name(account.member_id)} recherche un suppléant le {day.isoformat()}. Le premier ancien qui accepte s’engage à assurer son remplacement."
        for target in targets:notify(target,"SUBSTITUTION_OPEN","Suppléance recherchée",message,"substitutions")
        db.session.flush();audit(account,"REPLACEMENT_NEED_CREATED","replacement_need",x.id,day.isoformat());db.session.commit()
        payload=replacement_need_payload(x,account.member_id)
        payload["emailSentCount"]=sum(bool(replacement_mail(target,"Suppléance recherchée",message)) for target in targets)
        payload["notifiedCount"]=len(targets)
        return payload,201

    @app.route("/api/alumni-space/replacement-needs/<int:item_id>",methods=["POST","DELETE"])
    def respond_replacement_need(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(AlumniReplacementNeed,item_id)
        if not x:return {"error":"Besoin introuvable."},404
        if request.method=="DELETE":
            if x.official_id!=account.member_id or not official_member(account.member):return {"error":"Cette demande appartient à un autre membre."},403
            lock_replacement_members(x.official_id,*([x.alumni_id] if x.alumni_id else []))
            x=AlumniReplacementNeed.query.filter_by(id=item_id).with_for_update().populate_existing().first()
            if x.status=="CANCELLED":return replacement_need_payload(x,account.member_id)
            x.status="CANCELLED"
            if x.alumni_id:notify(x.alumni_id,"SUBSTITUTION_CANCELLED","Suppléance annulée",f"{member_name(x.official_id)} a annulé le remplacement du {x.date.isoformat()}.","substitutions")
            audit(account,"REPLACEMENT_NEED_CANCELLED","replacement_need",x.id);db.session.commit()
            if x.alumni_id:replacement_mail(x.alumni_id,"Suppléance annulée",f"{member_name(x.official_id)} a annulé le remplacement du {x.date.isoformat()}.")
            return replacement_need_payload(x,account.member_id)
        if not alumni_member(account.member):return {"error":"Seul un ancien peut accepter cette suppléance."},403
        lock_replacement_members(x.official_id,account.member_id)
        x=AlumniReplacementNeed.query.filter_by(id=item_id).with_for_update().populate_existing().first()
        official=db.session.get(Member,x.official_id)
        if not official_member(official):return {"error":"Ce membre ne fait plus partie des membres actifs."},403
        if x.status!="OPEN":return {"error":"Cette suppléance n’est plus disponible.","need":replacement_need_payload(x,account.member_id)},409
        if not future_replacement_meeting(x.date):return {"error":"Cette réunion n’est plus à venir ou a été annulée."},400
        if replacement_conflict(x.date,x.official_id,account.member_id,exclude_need=x.id):return {"error":"Un remplacement est déjà accepté pour ce membre ou pour vous à cette date."},409
        changed=AlumniReplacementNeed.query.filter_by(id=x.id,status="OPEN").update({"status":"ACCEPTED","alumni_id":account.member_id,"accepted_at":datetime.utcnow()},synchronize_session=False)
        if changed!=1:db.session.rollback();return {"error":"Un autre ancien a déjà accepté cette suppléance."},409
        db.session.refresh(x)
        message=f"{member_name(x.alumni_id)} a accepté de remplacer {member_name(x.official_id)} le {x.date.isoformat()}."
        message,_=replacement_notices(x,True)
        for m in Member.query.all():
            if m.id!=x.alumni_id and alumni_member(m) and m.user_account and m.user_account.status=="ACTIVE":notify(m.id,"SUBSTITUTION_FILLED","Votre engagement est confirmé" if m.id==x.alumni_id else "Suppléance pourvue",message,"substitutions")
        audit(account,"REPLACEMENT_NEED_ACCEPTED","replacement_need",x.id);db.session.commit()
        payload={**replacement_need_payload(x,account.member_id),**replacement_confirmation_emails(x,account,"replacement_need",message)}
        return payload

    @app.route("/api/alumni-space/availability",methods=["GET","POST"])
    def alumni_availability():
        account,err=replacement_account()
        if err:return err
        if request.method=="POST":
            if not alumni_member(account.member):return {"error":"Seuls les anciens proposent une suppléance."},403
            data=request.get_json(silent=True) or {}
            try:day=date.fromisoformat(data.get("date",""))
            except (ValueError,TypeError):return {"error":"Date invalide."},400
            if day<date.today():return {"error":"Choisissez une date à venir."},400
            x=AlumniAvailability.query.filter_by(member_id=account.member_id,date=day).first()
            if not x:x=AlumniAvailability(member_id=account.member_id,date=day);db.session.add(x)
            x.active=True;x.note=str(data.get("note") or "")[:500]
            db.session.commit();return availability_payload(x),201
        if alumni_member(account.member):
            rows=[x for x in visible_alumni_availability() if x.member_id==account.member_id]
        else:rows=visible_alumni_availability()
        return jsonify([availability_payload(x) for x in rows])

    @app.delete("/api/alumni-space/availability/<int:item_id>")
    def remove_alumni_availability(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(AlumniAvailability,item_id)
        if not x or x.member_id!=account.member_id:return {"error":"Disponibilité introuvable."},404
        x.active=False;db.session.commit();return {"ok":True}

    def substitution_payload(x):
        meeting=Meeting.query.filter_by(date=x.date).filter(Meeting.type!="NO_MEETING",Meeting.status!="CANCELLED").first()
        return {"id":x.id,"officialId":x.official_id,"official":member_name(x.official_id),"alumniId":x.alumni_id,"alumni":member_name(x.alumni_id),"date":x.date.isoformat(),"status":x.status,"location":meeting.location if meeting else None,"startTime":meeting.start_time.strftime("%H:%M") if meeting and meeting.start_time else None}

    @app.route("/api/alumni-space/substitutions",methods=["GET","POST"])
    def alumni_substitutions():
        account,err=replacement_account()
        if err:return err
        if request.method=="GET":
            rows=AlumniSubstitution.query.filter(db.or_(AlumniSubstitution.official_id==account.member_id,AlumniSubstitution.alumni_id==account.member_id)).order_by(AlumniSubstitution.date.desc()).all()
            return jsonify([substitution_payload(x) for x in rows])
        if not official_member(account.member):return {"error":"Seul un membre actif peut solliciter une suppléance."},403
        try:item_id=int((request.get_json(silent=True) or {}).get("availabilityId"))
        except (ValueError,TypeError):return {"error":"Disponibilité invalide."},400
        availability=db.session.get(AlumniAvailability,item_id)
        if not availability:return {"error":"Disponibilité introuvable."},404
        lock_replacement_members(account.member_id,availability.member_id)
        availability=AlumniAvailability.query.filter_by(id=item_id).with_for_update().populate_existing().first()
        if not availability or not availability.active or availability.date<date.today():return {"error":"Cette disponibilité n'est plus proposée."},400
        target=db.session.get(Member,availability.member_id)
        if not alumni_member(target) or not target.user_account or target.user_account.status!="ACTIVE":return {"error":"Cet ancien n'est plus disponible."},400
        meeting=future_replacement_meeting(availability.date)
        if not meeting:return {"error":"Aucune réunion n'est programmée à cette date."},400
        existing=AlumniSubstitution.query.filter_by(official_id=account.member_id,alumni_id=target.id,date=availability.date).filter(AlumniSubstitution.status.in_(["REQUESTED","ACCEPTED"])).first()
        if existing:return substitution_payload(existing)
        if AlumniSubstitution.query.filter_by(alumni_id=target.id,date=availability.date,status="ACCEPTED").first():return {"error":"Cet ancien est déjà engagé à cette date."},409
        if replacement_conflict(availability.date,account.member_id,target.id):return {"error":"Un remplacement est déjà accepté pour cette date."},409
        x=AlumniSubstitution(official_id=account.member_id,alumni_id=target.id,availability_id=availability.id,date=availability.date)
        db.session.add(x);db.session.flush();message,_=replacement_notices(x,False)
        audit(account,"ALUMNI_SUBSTITUTION_REQUESTED","substitution",x.id)
        db.session.commit()
        return {**substitution_payload(x),"emailSent":replacement_mail(x.official_id,"Suppléance à confirmer",message),"alumniEmailSent":replacement_mail(target.id,"Merci de confirmer votre suppléance",message)},201

    @app.post("/api/alumni-space/availability/<int:item_id>/accept")
    def accept_available_substitute(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not official_member(account.member):return {"error":"Seul un membre actif peut solliciter une suppléance."},403
        offer=db.session.get(AlumniAvailability,item_id)
        if not offer:return {"error":"Disponibilité introuvable."},404
        lock_replacement_members(account.member_id,offer.member_id)
        offer=AlumniAvailability.query.filter_by(id=item_id).with_for_update().populate_existing().first()
        member=db.session.get(Member,offer.member_id)
        if not official_member(account.member) or not offer.active or not alumni_member(member) or not member.user_account or member.user_account.status!="ACTIVE":return {"error":"Cette disponibilité n'est plus proposée."},409
        if not future_replacement_meeting(offer.date):return {"error":"Cette réunion n'est plus à venir ou a été annulée."},400
        if replacement_conflict(offer.date,account.member_id,member.id):return {"error":"Un remplacement est déjà confirmé pour cette date."},409
        pending=AlumniSubstitution.query.filter_by(official_id=account.member_id,date=offer.date,status="REQUESTED").all()
        for row in pending:row.status="CANCELLED"
        opened=AlumniReplacementNeed.query.filter_by(official_id=account.member_id,date=offer.date,status="OPEN").with_for_update().first()
        if opened:opened.status="CANCELLED"
        x=AlumniSubstitution(official_id=account.member_id,alumni_id=member.id,availability_id=offer.id,date=offer.date,status="ACCEPTED")
        db.session.add(x);db.session.flush()
        message=f"{member_name(account.member_id)} a accepté la proposition de suppléance de {member_name(member.id)} pour le {offer.date.strftime('%d/%m/%Y')}. Le remplacement est confirmé."
        message,_=replacement_notices(x,True)
        audit(account,"AVAILABLE_SUBSTITUTE_ACCEPTED","substitution",x.id,f"availability_id={offer.id}");db.session.commit()
        payload=substitution_payload(x)
        payload.update(replacement_confirmation_emails(x,account,"substitution",message))
        return payload,201

    @app.patch("/api/alumni-space/substitutions/<int:item_id>")
    def respond_alumni_substitution(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(AlumniSubstitution,item_id)
        if not x or account.member_id not in {x.official_id,x.alumni_id}:return {"error":"Demande introuvable."},404
        lock_replacement_members(x.official_id,x.alumni_id)
        x=AlumniSubstitution.query.filter_by(id=item_id).with_for_update().populate_existing().first()
        status=(request.get_json(silent=True) or {}).get("status")
        if status=="CANCELLED" and account.member_id==x.official_id:
            x.status=status
        elif account.member_id==x.alumni_id and alumni_member(account.member) and status in {"ACCEPTED","DECLINED"}:
            if x.status!="REQUESTED":return {"error":"Cette demande a déjà été traitée."},409
            if x.date<date.today():return {"error":"Cette date est passée."},400
            if status=="ACCEPTED":
                if not future_replacement_meeting(x.date):return {"error":"Cette réunion n’est plus à venir ou a été annulée."},400
                if replacement_conflict(x.date,x.official_id,x.alumni_id,exclude_target=x.id):return {"error":"Un remplacement est déjà accepté pour cette date."},409
                official=db.session.get(Member,x.official_id)
                if not official_member(official):return {"error":"Ce membre ne fait plus partie des membres actifs."},403
                AlumniAvailability.query.filter_by(id=x.availability_id).with_for_update().first()
                if AlumniSubstitution.query.filter(AlumniSubstitution.alumni_id==x.alumni_id,AlumniSubstitution.date==x.date,AlumniSubstitution.status=="ACCEPTED",AlumniSubstitution.id!=x.id).first():return {"error":"Une autre suppléance est déjà acceptée pour cette date."},409
            x.status=status
        else:return {"error":"Action non autorisée."},403
        other=x.official_id if account.member_id==x.alumni_id else x.alumni_id
        confirmation=f"{member_name(x.alumni_id)} a accepté de remplacer {member_name(x.official_id)} le {x.date.isoformat()}."
        if status=="ACCEPTED":confirmation,_=replacement_notices(x,True)
        else:notify(other,"SUBSTITUTION_RESPONSE","Suivi de suppléance",x.date.isoformat()+" : "+x.status,"substitutions")
        audit(account,"ALUMNI_SUBSTITUTION_UPDATED","substitution",x.id,status);db.session.commit()
        payload=substitution_payload(x)
        if status=="ACCEPTED":payload.update(replacement_confirmation_emails(x,account,"substitution",confirmation))
        return payload

    def member_name(member_id):
        m=db.session.get(Member,member_id)
        return f"{m.first_name} {m.last_name}" if m else "—"

    def member_payload(m):
        membership=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
        account=m.user_account
        return {"id":m.id,"environment":"ALUMNI" if alumni_member(m) else "MEMBERS" if official_member(m) else "INACTIVE","canActivateAlumniBridge":official_member(m),"alumniBridgeEnabled":bool(m.alumni_bridge_enabled),"firstName":m.first_name,"lastName":m.last_name,"company":m.company,"activity":m.activity,"email":m.email,"phone":m.phone,"networkType":m.network_type or "OFFICIAL_BNI","networkAccessEnabled":bool(m.network_access_enabled),"status":membership.status if membership else None,"startDate":membership.start_date.isoformat() if membership and membership.start_date else None,"endDate":membership.end_date.isoformat() if membership and membership.end_date else None,"alumniRequestedAt":m.alumni_requested_at.isoformat() if m.alumni_requested_at else None,"accountStatus":account.status if account else "NO_ACCOUNT","isSystemAdmin":bool(account and account.is_system_admin)}

    def member_entry_type(data):
        kind=data.get("memberType")
        if kind is None:
            kind="ALUMNI" if data.get("networkType")=="OFF" or data.get("status")=="OFF" else "BNI"
        if kind not in {"BNI","ALUMNI"}:return None,"Choisir Membre BNI ou Ancien membre."
        allowed={"OFF"} if kind=="ALUMNI" else {"ACTIVE","ONBOARDING"}
        if data.get("status") and data["status"] not in allowed:return None,"Le statut ne correspond pas au type de membre choisi."
        if data.get("networkType") and data["networkType"]!=("OFF" if kind=="ALUMNI" else "OFFICIAL_BNI"):return None,"Le réseau ne correspond pas au type de membre choisi."
        return kind,None

    @app.route("/api/members",methods=["GET","POST"])
    def members():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        if request.method=="POST":
            data=request.get_json(silent=True) or {}
            first=(data.get("firstName") or "").strip()
            last=(data.get("lastName") or "").strip()
            if not first or not last:
                return {"error":"firstName and lastName are required"},400
            email=(data.get("email") or "").strip() or None
            duplicate=Member.query.filter(db.func.lower(Member.first_name)==first.lower(),db.func.lower(Member.last_name)==last.lower()).first()
            if duplicate:
                return {"error":"Un membre avec ce prénom et ce nom existe déjà.","duplicateId":duplicate.id},409
            if email and Member.query.filter(db.func.lower(Member.email)==email.lower()).first():
                return {"error":"Un membre avec cet e-mail existe déjà."},409
            kind,error=member_entry_type(data)
            if error:return {"error":error},400
            member=Member(first_name=first,last_name=last,company=(data.get("company") or "").strip() or None,activity=(data.get("activity") or "").strip() or None,email=email.lower() if email else None,phone=(data.get("phone") or "").strip() or None,network_type="OFF" if kind=="ALUMNI" else "OFFICIAL_BNI",network_access_enabled=kind=="ALUMNI",alumni_bridge_enabled=False)
            db.session.add(member)
            db.session.flush()
            member_status="OFF" if kind=="ALUMNI" else ("ONBOARDING" if data.get("status")=="ONBOARDING" else "ACTIVE")
            membership=Membership(member_id=member.id,start_date=date.today(),status=member_status)
            db.session.add(membership)
            db.session.add(MemberNetworkHistory(member_id=member.id,network_type=member.network_type,start_date=date.today()))
            db.session.commit()
            return member_payload(member),201
        rows=Member.query.order_by(Member.last_name,Member.first_name).all()
        return jsonify([member_payload(m) for m in rows])

    V2_FEATURES={
        "NETWORK_MODULE":("Module Réseau","Afficher le menu Réseau aux membres autorisés."),
        "OFF_MEMBERSHIP":("Adhésions Membres OFF","Activer les offres et inscriptions au réseau OFF."),
        "OFF_PLAN_TRIAL":("Formule OFF · Test 1 mois","Proposer la formule test 1 mois à 100 € HTVA + petit déjeuner."),
        "OFF_PLAN_ANNUAL":("Formule OFF · 1 an","Proposer l'inscription annuelle à 600 € HTVA + petit déjeuner."),
        "OFF_PLAN_FREE":("Formule OFF · Gratuit / test","Proposer une période gratuite aux anciens membres."),
        "OFF_FORMER_HOME_OFFER":("Proposition OFF aux anciens","Afficher automatiquement aux membres anciens la possibilité de rester dans le réseau OFF."),
        "REFERRALS":("Recommandations","Encoder et suivre les recommandations entre membres."),
        "BUSINESS":("Business généré","Encoder les Merci pour le Business et le chiffre d'affaires généré."),
        "ONE_TO_ONE":("Tête-à-Tête","Encoder les rendez-vous individuels entre membres."),
        "VISITORS":("Invités","Encoder et suivre les invités amenés au groupe."),
        "ATTENDANCE":("Présences","Mesurer les présences, suppléants et absences."),
        "NETWORK_OFF":("Réseau OFF","Activer les membres du réseau OFF."),
        "MEMBERSHIP_CHOICE":("Choix HUB / OFF","Permettre de choisir le réseau à l'entrée d'un nouveau membre."),
        "ACTIVITY_SCORE":("Indice d'engagement","Calculer le score interne d'activité et les couleurs.")
    }

    @app.get("/api/system/features")
    def system_features():
        account,err=require_system_admin()
        if err:return err
        rows={x.key:x for x in FeatureFlag.query.all()}
        return jsonify([{"key":k,"label":label,"description":desc,"enabled":bool(rows.get(k) and rows[k].enabled)} for k,(label,desc) in V2_FEATURES.items()])

    @app.put("/api/system/features/<key>")
    def system_feature_update(key):
        account,err=require_system_admin()
        if err:return err
        key=key.strip().upper()
        if key not in V2_FEATURES:return {"error":"Fonctionnalité inconnue."},404
        data=request.get_json(silent=True) or {}
        row=db.session.get(FeatureFlag,key)
        if not row:
            label,desc=V2_FEATURES[key];row=FeatureFlag(key=key,label=label,description=desc);db.session.add(row)
        row.enabled=bool(data.get("enabled"))
        audit(account,"FEATURE_FLAG_UPDATED","feature_flag",key,f"enabled={row.enabled}")
        db.session.commit()
        return {"key":key,"enabled":row.enabled}

    @app.post("/api/members/<int:member_id>/network")
    def system_change_member_network(member_id):
        account,err=require_system_admin()
        if err:return err
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        data=request.get_json(silent=True) or {}
        network_type=(data.get("networkType") or "").strip().upper()
        if network_type not in {"OFFICIAL_BNI","OFF","TRANSITION"}:return {"error":"Type de réseau invalide."},400
        if network_type=="OFF" and official_member(member) and not member.alumni_requested_at:return {"error":"Le membre doit demander personnellement son passage chez les anciens."},400
        effective=date.today()
        if data.get("effectiveDate"):
            try:effective=date.fromisoformat(data["effectiveDate"])
            except ValueError:return {"error":"Date de bascule invalide."},400
        current=MemberNetworkHistory.query.filter_by(member_id=member.id,end_date=None).order_by(MemberNetworkHistory.start_date.desc()).first()
        if current and current.network_type==network_type:
            # The member may already have been switched to this network by another workflow
            # (e.g. activating an OFF membership). In that case, allow the system admin
            # to correct the effective date instead of silently ignoring it.
            current.start_date=effective
            previous=MemberNetworkHistory.query.filter(
                MemberNetworkHistory.member_id==member.id,
                MemberNetworkHistory.id!=current.id
            ).order_by(MemberNetworkHistory.start_date.desc(),MemberNetworkHistory.id.desc()).first()
            if previous and previous.start_date<effective:
                previous.end_date=effective-timedelta(days=1)
            member.network_type=network_type
            if network_type=="OFF":
                membership=active_membership_for(member.id)
                if membership:membership.status="OFF"
                member.alumni_bridge_enabled=False
            if network_type=="OFF":
                member.network_access_enabled=True
                ensure_off_network_features()
            audit(account,"MEMBER_NETWORK_DATE_UPDATED","member",member.id,f"{network_type}; effective={effective.isoformat()}")
            db.session.commit()
            return member_payload(member)
        if current:current.end_date=effective-timedelta(days=1)
        member.network_type=network_type
        if network_type=="OFF":
            membership=active_membership_for(member.id)
            if membership:membership.status="OFF"
            member.alumni_bridge_enabled=False
        if network_type=="OFF":
            member.network_access_enabled=True
            ensure_off_network_features()
        db.session.add(MemberNetworkHistory(member_id=member.id,network_type=network_type,start_date=effective,changed_by_account_id=account.id))
        audit(account,"MEMBER_NETWORK_CHANGED","member",member.id,f"{current.network_type if current else 'UNKNOWN'}->{network_type}; effective={effective.isoformat()}")
        db.session.commit()
        return member_payload(member)

    @app.get("/api/members/<int:member_id>/network-history")
    def member_network_history(member_id):
        _,err=require_admin()
        if err:return err
        rows=MemberNetworkHistory.query.filter_by(member_id=member_id).order_by(MemberNetworkHistory.start_date.desc(),MemberNetworkHistory.id.desc()).all()
        return jsonify([{"id":x.id,"networkType":x.network_type,"startDate":x.start_date.isoformat(),"endDate":x.end_date.isoformat() if x.end_date else None} for x in rows])

    REFERRAL_STATUSES={"PENDING","NO_FOLLOW_UP","WON","LOST"}

    @app.get("/api/network/config")
    def network_config():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        enabled=full_network_enabled(account)
        return {"features":{k:enabled for k in ["REFERRALS","BUSINESS","ONE_TO_ONE","ACTIVITY_SCORE"]},"networkType":account.member.network_type,"networkAccessEnabled":enabled,"networkModuleEnabled":enabled,"networkBridgeEnabled":network_bridge_enabled(account),"fullNetworkEnabled":enabled,"isSystemAdmin":False,"environment":"ALUMNI" if alumni_member(account.member) else "MEMBERS"}

    @app.get("/api/directory")
    def member_directory():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        official=official_member(account.member)
        if not official and not alumni_member(account.member):
            return {"error":"Réservé aux membres et anciens actifs."},403
        out=[]
        for member in Member.query.order_by(Member.last_name,Member.first_name,Member.id).all():
            current=official_member(member)
            activated=bool(member.user_account and member.user_account.status=="ACTIVE")
            if current:
                # Alumni only see officials who personally opted into business contact.
                if not official and not (activated and member.alumni_bridge_enabled):continue
                category="MEMBERS"
            elif alumni_member(member) and activated:category="ALUMNI"
            else:continue
            out.append({"id":member.id,"firstName":member.first_name,"lastName":member.last_name,
                "company":member.company,"activity":member.activity,"phone":member.phone,
                "email":member.email or (member.user_account.email if activated else None),"category":category})
        return jsonify(out)

    @app.get("/api/network/members")
    def network_members():
        account,err=require_feature("REFERRALS")
        if err:return err
        rows=Member.query.order_by(Member.last_name,Member.first_name).all()
        out=[]
        for m in rows:
            if not m.user_account or m.user_account.status!="ACTIVE":continue
            if not bridge_pair_allowed(account,m.id) and m.id!=account.member_id:continue
            out.append({"id":m.id,"name":f"{m.first_name} {m.last_name}","company":m.company,"activity":m.activity,"networkType":m.network_type or "OFFICIAL_BNI"})
        return jsonify(out)

    def bridge_pair_allowed(account,other_member_id):
        other=db.session.get(Member,other_member_id)
        if not other or other.id==account.member_id:return False
        # A member record or pending invitation is not an activated HUB account.
        # Keep the recipient list and all three encoding endpoints consistent.
        if not other.user_account or other.user_account.status!="ACTIVE":return False
        own_alumni=alumni_member(account.member);other_alumni=alumni_member(other)
        own_opted=official_member(account.member) and account.member.alumni_bridge_enabled
        other_opted=official_member(other) and other.alumni_bridge_enabled
        return bool((own_alumni and (other_alumni or other_opted)) or (own_opted and (other_alumni or other_opted)))

    def referral_payload(x):
        return {"id":x.id,"fromMemberId":x.from_member_id,"fromMember":member_name(x.from_member_id),"toMemberId":x.to_member_id,"toMember":member_name(x.to_member_id),"contactName":x.contact_name,"company":x.company,"contactEmail":x.contact_email,"contactPhone":x.contact_phone,"notes":x.notes,"status":x.status,"estimatedValue":float(x.estimated_value) if x.estimated_value is not None else None,"closedAt":x.closed_at.isoformat() if x.closed_at else None,"businessAmount":float((BusinessThanks.query.filter_by(referral_id=x.id).first().amount)) if BusinessThanks.query.filter_by(referral_id=x.id).first() else None,"createdAt":x.created_at.isoformat(),"updatedAt":x.updated_at.isoformat() if x.updated_at else None}

    @app.route("/api/network/referrals",methods=["GET","POST"])
    def network_referrals():
        account,err=require_feature("REFERRALS")
        if err:return err
        if request.method=="POST":
            data=request.get_json(silent=True) or {}
            try:to_id=int(data.get("toMemberId"))
            except (TypeError,ValueError):return {"error":"Membre destinataire requis."},400
            if to_id==account.member_id:return {"error":"Vous ne pouvez pas vous envoyer une recommandation à vous-même."},400
            if not db.session.get(Member,to_id):return {"error":"Membre destinataire introuvable."},404
            if not bridge_pair_allowed(account,to_id):return {"error":"Cette interaction nécessite un ancien et, pour un membre actif, sa liaison personnelle activée."},403
            contact=(data.get("contactName") or "").strip()
            if not contact:return {"error":"Le nom du contact recommandé est obligatoire."},400
            estimated=None
            if str(data.get("estimatedValue") or "").strip():
                try:estimated=float(data["estimatedValue"])
                except (TypeError,ValueError):return {"error":"Valeur estimée invalide."},400
            x=Referral(from_member_id=account.member_id,to_member_id=to_id,contact_name=contact,company=(data.get("company") or "").strip() or None,contact_email=(data.get("contactEmail") or "").strip() or None,contact_phone=(data.get("contactPhone") or "").strip() or None,notes=(data.get("notes") or "").strip() or None,estimated_value=estimated,status="PENDING")
            db.session.add(x);db.session.flush()
            db.session.add(ReferralStatusHistory(referral_id=x.id,status="PENDING",note="Recommandation créée — pas encore contactée",changed_by_member_id=account.member_id))
            notify(to_id,"REFERRAL_RECEIVED","Nouvelle recommandation",f"{account.member.first_name} {account.member.last_name} vous a transmis une recommandation : {contact}.","network")
            audit(account,"REFERRAL_CREATED","referral",x.id,f"to={to_id}")
            db.session.commit()
            referral_email(x)
            return referral_payload(x),201
        q=Referral.query
        q=q.filter(db.or_(Referral.from_member_id==account.member_id,Referral.to_member_id==account.member_id))
        rows=q.order_by(Referral.created_at.desc()).limit(500).all()
        if not account.is_system_admin and not full_network_enabled(account):
            rows=[x for x in rows if (db.session.get(Member,x.from_member_id).network_type=="OFF" or db.session.get(Member,x.to_member_id).network_type=="OFF")]
        return jsonify([referral_payload(x) for x in rows])

    @app.patch("/api/network/referrals/<int:referral_id>")
    def network_referral_update(referral_id):
        account,err=require_feature("REFERRALS")
        if err:return err
        x=db.session.get(Referral,referral_id)
        if not x:return {"error":"Recommandation introuvable."},404
        if account.member_id!=x.to_member_id and not account_payload(account)["isAdmin"]:return {"error":"Le suivi doit être effectué par le membre qui a reçu la recommandation."},403
        other_id=x.from_member_id if account.member_id==x.to_member_id else x.to_member_id
        if not bridge_pair_allowed(account,other_id):return {"error":"Cette interaction nécessite un ancien et, pour un membre actif, sa liaison personnelle activée."},403
        data=request.get_json(silent=True) or {}
        status=(data.get("status") or "").strip().upper()
        if status not in REFERRAL_STATUSES:return {"error":"Statut invalide."},400
        note=(data.get("note") or "").strip() or None
        new_business=False
        if status=="WON":
            try:amount=float(data.get("amount"))
            except (TypeError,ValueError):return {"error":"Encodez le chiffre d'affaires généré pour clôturer une affaire gagnée."},400
            if amount<=0:return {"error":"Le chiffre d'affaires doit être supérieur à 0."},400
            existing=BusinessThanks.query.filter_by(referral_id=x.id).first()
            if not existing:
                existing=BusinessThanks(from_member_id=x.to_member_id,credited_member_id=x.from_member_id,referral_id=x.id,amount=amount,business_date=date.today(),notes=note)
                db.session.add(existing);new_business=True
            else:
                existing.amount=amount;existing.notes=note
        x.status=status
        x.closed_at=datetime.utcnow() if status in {"NO_FOLLOW_UP","WON","LOST"} else None
        db.session.add(ReferralStatusHistory(referral_id=x.id,status=status,note=note,changed_by_member_id=account.member_id))
        labels={"PENDING":"Pas encore contacté","NO_FOLLOW_UP":"Contacté — pas de suite","WON":"Affaire gagnée","LOST":"Marché perdu"}
        notify(x.from_member_id,"REFERRAL_UPDATED","Suivi de recommandation",f"{x.contact_name} : {labels.get(status,status)}.","network")
        audit(account,"REFERRAL_STATUS_UPDATED","referral",x.id,status)
        db.session.commit()
        if new_business:network_email(x.to_member_id,x.from_member_id,"un MPB","business")
        return referral_payload(x)

    @app.get("/api/network/referrals/<int:referral_id>/history")
    def network_referral_history(referral_id):
        account,err=require_feature("REFERRALS")
        if err:return err
        x=db.session.get(Referral,referral_id)
        if not x:return {"error":"Recommandation introuvable."},404
        if account.member_id not in {x.from_member_id,x.to_member_id} and not account_payload(account)["isAdmin"]:return {"error":"Accès refusé."},403
        other_id=x.from_member_id if account.member_id==x.to_member_id else x.to_member_id
        if account.member_id in {x.from_member_id,x.to_member_id} and not bridge_pair_allowed(account,other_id):return {"error":"Cette interaction nécessite un ancien et, pour un membre actif, sa liaison personnelle activée."},403
        rows=ReferralStatusHistory.query.filter_by(referral_id=x.id).order_by(ReferralStatusHistory.created_at.desc()).all()
        return jsonify([{"id":h.id,"status":h.status,"note":h.note,"changedBy":member_name(h.changed_by_member_id),"createdAt":h.created_at.isoformat()} for h in rows])

    def business_payload(x):
        return {"id":x.id,"fromMemberId":x.from_member_id,"fromMember":member_name(x.from_member_id),"creditedMemberId":x.credited_member_id,"creditedMember":member_name(x.credited_member_id),"referralId":x.referral_id,"amount":float(x.amount),"notes":x.notes,"businessDate":x.business_date.isoformat(),"createdAt":x.created_at.isoformat()}

    @app.route("/api/network/business",methods=["GET","POST"])
    def network_business():
        account,err=require_feature("BUSINESS")
        if err:return err
        if request.method=="POST":
            data=request.get_json(silent=True) or {}
            try:credited=int(data.get("creditedMemberId"));amount=float(data.get("amount"))
            except (TypeError,ValueError):return {"error":"Membre et montant valides requis."},400
            if credited==account.member_id:return {"error":"Le Merci pour le Business doit créditer un autre membre."},400
            if amount<=0:return {"error":"Le montant doit être supérieur à 0."},400
            if not db.session.get(Member,credited):return {"error":"Membre introuvable."},404
            if not bridge_pair_allowed(account,credited):return {"error":"Cette interaction nécessite un ancien et, pour un membre actif, sa liaison personnelle activée."},403
            business_date=date.today()
            if data.get("businessDate"):
                try:business_date=date.fromisoformat(data["businessDate"])
                except ValueError:return {"error":"Date invalide."},400
            referral_id=None
            if data.get("referralId"):
                try:referral_id=int(data["referralId"])
                except (TypeError,ValueError):return {"error":"Recommandation invalide."},400
            x=BusinessThanks(from_member_id=account.member_id,credited_member_id=credited,referral_id=referral_id,amount=amount,business_date=business_date,notes=(data.get("notes") or "").strip() or None)
            db.session.add(x);db.session.flush()
            notify(credited,"BUSINESS_THANKS","Merci pour le Business",f"{account.member.first_name} {account.member.last_name} vous crédite de {amount:,.2f} € de business généré.","network")
            audit(account,"BUSINESS_THANKS_CREATED","business_thanks",x.id,f"credited={credited};amount={amount}")
            db.session.commit()
            network_email(account.member_id,credited,"un MPB","business")
            return business_payload(x),201
        q=BusinessThanks.query
        q=q.filter(db.or_(BusinessThanks.from_member_id==account.member_id,BusinessThanks.credited_member_id==account.member_id))
        return jsonify([business_payload(x) for x in q.order_by(BusinessThanks.business_date.desc(),BusinessThanks.id.desc()).limit(500).all()])

    @app.route("/api/network/one-to-ones",methods=["GET","POST"])
    def network_one_to_ones():
        account,err=require_feature("ONE_TO_ONE")
        if err:return err
        if request.method=="POST":
            data=request.get_json(silent=True) or {}
            try:partner=int(data.get("partnerMemberId"))
            except (TypeError,ValueError):return {"error":"Membre partenaire requis."},400
            if partner==account.member_id:return {"error":"Choisissez un autre membre."},400
            if not db.session.get(Member,partner):return {"error":"Membre introuvable."},404
            if not bridge_pair_allowed(account,partner):return {"error":"Cette interaction nécessite un ancien et, pour un membre actif, sa liaison personnelle activée."},403
            d=date.today()
            if data.get("meetingDate"):
                try:d=date.fromisoformat(data["meetingDate"])
                except ValueError:return {"error":"Date invalide."},400
            duration=None
            if data.get("durationMinutes"):
                try:duration=int(data["durationMinutes"])
                except (TypeError,ValueError):return {"error":"Durée invalide."},400
            x=OneToOne(member_a_id=account.member_id,member_b_id=partner,meeting_date=d,duration_minutes=duration,notes=(data.get("notes") or "").strip() or None,created_by_member_id=account.member_id)
            db.session.add(x);db.session.flush()
            notify(partner,"ONE_TO_ONE_RECORDED","Tête-à-Tête encodé",f"{account.member.first_name} {account.member.last_name} a enregistré un Tête-à-Tête avec vous.","network")
            audit(account,"ONE_TO_ONE_CREATED","one_to_one",x.id,f"partner={partner}")
            db.session.commit()
            network_email(account.member_id,partner,"un TAT","oto")
            return {"id":x.id,"partner":member_name(partner),"meetingDate":d.isoformat(),"durationMinutes":duration,"notes":x.notes},201
        q=OneToOne.query
        q=q.filter(db.or_(OneToOne.member_a_id==account.member_id,OneToOne.member_b_id==account.member_id))
        rows=q.order_by(OneToOne.meeting_date.desc(),OneToOne.id.desc()).limit(500).all()
        return jsonify([{"id":x.id,"memberAId":x.member_a_id,"memberA":member_name(x.member_a_id),"memberBId":x.member_b_id,"memberB":member_name(x.member_b_id),"meetingDate":x.meeting_date.isoformat(),"durationMinutes":x.duration_minutes,"notes":x.notes} for x in rows])

    @app.route("/api/network/visitors",methods=["GET","POST"])
    def network_visitors():
        account,err=require_feature("VISITORS")
        if err:return err
        if request.method=="POST":
            data=request.get_json(silent=True) or {}
            name=(data.get("name") or "").strip()
            if not name:return {"error":"Nom de l'invité obligatoire."},400
            d=date.today()
            if data.get("visitDate"):
                try:d=date.fromisoformat(data["visitDate"])
                except ValueError:return {"error":"Date invalide."},400
            x=NetworkVisitor(invited_by_member_id=account.member_id,name=name,company=(data.get("company") or "").strip() or None,activity=(data.get("activity") or "").strip() or None,email=(data.get("email") or "").strip() or None,phone=(data.get("phone") or "").strip() or None,visit_date=d,status="INVITED",notes=(data.get("notes") or "").strip() or None)
            db.session.add(x);db.session.flush();audit(account,"VISITOR_CREATED","network_visitor",x.id,name);db.session.commit()
            return {"id":x.id,"name":x.name,"company":x.company,"activity":x.activity,"visitDate":x.visit_date.isoformat(),"status":x.status},201
        q=NetworkVisitor.query
        q=q.filter_by(invited_by_member_id=account.member_id)
        rows=q.order_by(NetworkVisitor.visit_date.desc(),NetworkVisitor.id.desc()).limit(500).all()
        return jsonify([{"id":x.id,"invitedByMemberId":x.invited_by_member_id,"invitedBy":member_name(x.invited_by_member_id),"name":x.name,"company":x.company,"activity":x.activity,"email":x.email,"phone":x.phone,"visitDate":x.visit_date.isoformat(),"status":x.status,"notes":x.notes} for x in rows])

    @app.patch("/api/network/visitors/<int:visitor_id>")
    def network_visitor_update(visitor_id):
        account,err=require_feature("VISITORS")
        if err:return err
        x=db.session.get(NetworkVisitor,visitor_id)
        if not x:return {"error":"Invité introuvable."},404
        if x.invited_by_member_id!=account.member_id and not account_payload(account)["isAdmin"]:return {"error":"Accès refusé."},403
        status=(request.get_json(silent=True) or {}).get("status","").upper()
        if status not in {"INVITED","ATTENDED","FOLLOW_UP","JOINED","DECLINED"}:return {"error":"Statut invalide."},400
        x.status=status;db.session.commit();return {"id":x.id,"status":x.status}

    @app.put("/api/network/attendance/<int:meeting_id>/<int:member_id>")
    def network_attendance_update(meeting_id,member_id):
        account,err=require_admin()
        if err:return err
        if not feature_enabled("ATTENDANCE") and not account.is_system_admin:return {"error":"Fonctionnalité non activée."},403
        if not db.session.get(Meeting,meeting_id) or not db.session.get(Member,member_id):return {"error":"Réunion ou membre introuvable."},404
        data=request.get_json(silent=True) or {};status=(data.get("status") or "").upper()
        if status not in {"PRESENT","SUBSTITUTE","ABSENT","EXCUSED"}:return {"error":"Statut de présence invalide."},400
        x=AttendanceRecord.query.filter_by(meeting_id=meeting_id,member_id=member_id).first()
        if not x:x=AttendanceRecord(meeting_id=meeting_id,member_id=member_id);db.session.add(x)
        x.status=status;x.notes=(data.get("notes") or "").strip() or None
        audit(account,"ATTENDANCE_UPDATED","attendance",f"{meeting_id}:{member_id}",status);db.session.commit()
        return {"meetingId":meeting_id,"memberId":member_id,"status":status}

    def correction_payload(kind,x):
        if kind=="business":
            result={"id":x.id,"kind":kind,"date":x.business_date.isoformat(),"amount":str(x.amount),"fromMember":member_name(x.from_member_id),"toMember":member_name(x.credited_member_id),"notes":x.notes,"referralId":x.referral_id}
        elif kind=="one-to-ones":
            result={"id":x.id,"kind":kind,"date":x.meeting_date.isoformat(),"fromMember":member_name(x.member_a_id),"toMember":member_name(x.member_b_id),"durationMinutes":x.duration_minutes,"notes":x.notes}
        else:
            result={"id":x.id,"kind":kind,"date":x.created_at.date().isoformat(),"fromMember":member_name(x.from_member_id),"toMember":member_name(x.to_member_id),"contactName":x.contact_name,"estimatedValue":str(x.estimated_value) if x.estimated_value is not None else None,"status":x.status,"notes":x.notes}
        import hashlib,json
        result["version"]=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
        return result

    @app.get("/api/admin/network-records")
    def admin_activity_records():
        account,err=require_admin()
        if err:return err
        kind=request.args.get("kind","business")
        model={"business":BusinessThanks,"one-to-ones":OneToOne,"referrals":Referral}.get(kind)
        if not model:return {"error":"Type d'encodage invalide."},400
        try:offset=max(0,int(request.args.get("offset",0)))
        except ValueError:return {"error":"Page invalide."},400
        query=model.query
        text_query=request.args.get("q","").strip()
        if text_query:
            ids=db.session.query(Member.id).filter(db.or_((Member.first_name+" "+Member.last_name).ilike("%"+text_query+"%"),Member.company.ilike("%"+text_query+"%")))
            left=model.from_member_id if kind!="one-to-ones" else model.member_a_id
            right=model.credited_member_id if kind=="business" else model.to_member_id if kind=="referrals" else model.member_b_id
            query=query.filter(db.or_(left.in_(ids),right.in_(ids)))
        date_column=model.business_date if kind=="business" else model.meeting_date if kind=="one-to-ones" else model.created_at
        rows=query.order_by(date_column.desc(),model.id.desc()).offset(offset).limit(101).all()
        return {"items":[correction_payload(kind,x) for x in rows[:100]],"hasMore":len(rows)>100,"offset":offset}

    @app.route("/api/admin/network-records/<kind>/<int:record_id>",methods=["PATCH","DELETE"])
    def correct_activity_record(kind,record_id):
        account,err=require_admin()
        if err:return err
        model={"business":BusinessThanks,"one-to-ones":OneToOne,"referrals":Referral}.get(kind)
        if not model:return {"error":"Type d'encodage invalide."},400
        x=model.query.filter_by(id=record_id).with_for_update().first()
        if not x:return {"error":"Encodage introuvable ou déjà supprimé."},404
        data=request.get_json(silent=True) or {}
        reason=str(data.get("reason") or "").strip()
        if len(reason)<3 or len(reason)>500:return {"error":"Un motif de correction de 3 à 500 caractères est obligatoire."},400
        before=correction_payload(kind,x)
        if data.get("version")!=before["version"]:return {"error":"Cet encodage a changé. Rechargez la liste avant de le corriger."},409
        related=None
        if request.method=="DELETE":
            if kind=="referrals":
                if BusinessThanks.query.filter_by(referral_id=x.id).first():return {"error":"Cette recommandation possède un MPB. Corrigez ou supprimez d’abord ce MPB."},409
                ReferralStatusHistory.query.filter_by(referral_id=x.id).delete(synchronize_session=False)
            if kind=="business" and x.referral_id:
                referral=Referral.query.filter_by(id=x.referral_id).with_for_update().first()
                other=BusinessThanks.query.filter(BusinessThanks.referral_id==x.referral_id,BusinessThanks.id!=x.id).first()
                if referral and referral.status=="WON" and not other:
                    related={"referralId":referral.id,"beforeStatus":referral.status,"afterStatus":"PENDING","closedAt":referral.closed_at.isoformat() if referral.closed_at else None}
                    referral.status="PENDING";referral.closed_at=None
                    db.session.add(ReferralStatusHistory(referral_id=referral.id,status="PENDING",note="Correction administrative : suppression du dernier MPB lié. "+reason,changed_by_member_id=account.member_id))
            db.session.delete(x);after=None
        else:
            try:day=date.fromisoformat(str(data.get("date",before["date"])))
            except ValueError:return {"error":"Date invalide."},400
            from decimal import Decimal,InvalidOperation
            field="amount" if kind=="business" else "estimatedValue"
            amount=None
            if kind!="one-to-ones" and str(data.get(field) or "").strip():
                try:
                    amount=Decimal(str(data[field]))
                    if not amount.is_finite() or amount<0 or amount>Decimal("9999999999.99") or (kind=="business" and amount==0):raise InvalidOperation()
                    amount=amount.quantize(Decimal("0.01"))
                    if kind=="business" and amount<=0:raise InvalidOperation()
                except (InvalidOperation,ValueError):return {"error":"Montant invalide."},400
            if kind=="business" and amount is None:return {"error":"Un montant positif est requis."},400
            duration=None
            if kind=="one-to-ones" and str(data.get("durationMinutes") or "").strip():
                try:
                    duration=int(data["durationMinutes"])
                    if duration<1 or duration>1440:raise ValueError()
                except (ValueError,TypeError):return {"error":"Durée invalide (1 à 1440 minutes)."},400
            if kind=="business":x.amount=amount;x.business_date=day
            elif kind=="one-to-ones":x.meeting_date=day;x.duration_minutes=duration
            else:x.created_at=datetime.combine(day,x.created_at.time());x.estimated_value=amount
            if "notes" in data:x.notes=str(data["notes"] or "").strip() or None
            db.session.flush();after=correction_payload(kind,x)
        import json
        audit(account,"ACTIVITY_DELETED" if after is None else "ACTIVITY_CORRECTED","network_"+kind,record_id,json.dumps({"reason":reason,"before":before,"after":after,"related":related},ensure_ascii=False))
        db.session.commit()
        return {"status":"DELETED" if after is None else "CORRECTED","record":after}

    @app.get("/api/admin/network-records/history")
    def activity_correction_history():
        account,err=require_admin()
        if err:return err
        import json
        rows=AuditLog.query.filter(AuditLog.action.in_(["ACTIVITY_CORRECTED","ACTIVITY_DELETED"])).order_by(AuditLog.created_at.desc(),AuditLog.id.desc()).limit(100).all()
        return jsonify([{"id":x.id,"date":x.created_at.isoformat()+"Z","actor":member_name(x.member_id),"action":x.action,"recordId":x.entity_id,"details":json.loads(x.details)} for x in rows])

    @app.get("/api/network/stats")
    def network_stats():
        account,err=require_feature("ACTIVITY_SCORE")
        if err:return err
        member_id=account.member_id
        if request.args.get("memberId") and account_payload(account)["isAdmin"]:
            try:member_id=int(request.args["memberId"])
            except ValueError:return {"error":"Membre invalide."},400
        return member_statistics(member_id,personal_activity_period(member_id))

    def member_statistics(member_id,mandate):
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        start=mandate.start_date if mandate else today
        end=min(today,mandate.end_date) if mandate else today-timedelta(days=1)
        end_dt=datetime.combine(end+timedelta(days=1),datetime.min.time())
        months=max(1,((end.year-start.year)*12+end.month-start.month+1))
        refs_given=Referral.query.filter(Referral.from_member_id==member_id,Referral.created_at>=start,Referral.created_at<end_dt).count()
        refs_received=Referral.query.filter(Referral.to_member_id==member_id,Referral.created_at>=start,Referral.created_at<end_dt).count()
        refs_won=Referral.query.filter(Referral.to_member_id==member_id,Referral.status=="WON",Referral.created_at>=start,Referral.created_at<end_dt).count()
        one_to_ones=OneToOne.query.filter(db.or_(OneToOne.member_a_id==member_id,OneToOne.member_b_id==member_id),OneToOne.meeting_date>=start,OneToOne.meeting_date<=end).count()
        visitors=NetworkVisitor.query.filter(NetworkVisitor.invited_by_member_id==member_id,NetworkVisitor.visit_date>=start,NetworkVisitor.visit_date<=end).count()
        generated=float(db.session.query(db.func.coalesce(db.func.sum(BusinessThanks.amount),0)).filter(BusinessThanks.credited_member_id==member_id,BusinessThanks.business_date>=start,BusinessThanks.business_date<=end).scalar() or 0)
        received=float(db.session.query(db.func.coalesce(db.func.sum(BusinessThanks.amount),0)).filter(BusinessThanks.from_member_id==member_id,BusinessThanks.business_date>=start,BusinessThanks.business_date<=end).scalar() or 0)
        attendance=AttendanceRecord.query.join(Meeting,Meeting.id==AttendanceRecord.meeting_id).filter(AttendanceRecord.member_id==member_id,Meeting.date>=start,Meeting.date<=end).all()
        counted=[a for a in attendance if a.status in {"PRESENT","SUBSTITUTE","ABSENT"}]
        attendance_rate=100.0 if not counted else round(100*sum(1 for a in counted if a.status in {"PRESENT","SUBSTITUTE"})/len(counted),1)
        monthly=max(1,months)
        ref_score=min(35,35*(refs_given/monthly)/5)
        oto_score=min(25,25*(one_to_ones/monthly)/2)
        visitor_score=min(20,20*(visitors/monthly))
        attendance_score=min(20,20*attendance_rate/100)
        score=round(ref_score+oto_score+visitor_score+attendance_score)
        color="GREEN" if score>=70 else "YELLOW" if score>=50 else "RED" if score>=30 else "GREY"
        conversion=round(100*refs_won/refs_received,1) if refs_received else 0
        estimated_given=float(db.session.query(db.func.coalesce(db.func.sum(Referral.estimated_value),0)).filter(Referral.from_member_id==member_id,Referral.created_at>=start,Referral.created_at<end_dt).scalar() or 0)
        estimated_received=float(db.session.query(db.func.coalesce(db.func.sum(Referral.estimated_value),0)).filter(Referral.to_member_id==member_id,Referral.created_at>=start,Referral.created_at<end_dt).scalar() or 0)
        avg_won_value=round(received/refs_won,2) if refs_won else 0
        return {"memberId":member_id,"member":member_name(member_id),"months":months,"periodStart":start.isoformat(),"periodEnd":end.isoformat(),"mandateId":mandate.id if mandate else None,"mandate":mandate.name if mandate else "Aucune mandature en cours","referralsGiven":refs_given,"referralsReceived":refs_received,"referralsWon":refs_won,"conversionRate":conversion,"oneToOnes":one_to_ones,"visitors":visitors,"businessGenerated":generated,"businessReceived":received,"estimatedValueGiven":estimated_given,"estimatedValueReceived":estimated_received,"averageWonReferralValue":avg_won_value,"attendanceRate":attendance_rate,"score":score,"scoreColor":color,"scoreBreakdown":{"referrals":round(ref_score,1),"oneToOnes":round(oto_score,1),"visitors":round(visitor_score,1),"attendance":round(attendance_score,1)},"targets":{"referralsPerMonth":5,"oneToOnesPerMonth":2,"visitorsPerMonth":1,"absenceTarget":0}}

    @app.get("/api/me/past-stats")
    def past_member_stats():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        mandates=Mandate.query.filter(Mandate.end_date<today).order_by(Mandate.start_date.desc()).all()
        options=[{"id":m.id,"name":m.name,"startDate":m.start_date.isoformat(),"endDate":m.end_date.isoformat()} for m in mandates]
        selected=None
        if request.args.get("mandateId"):
            try:selected=next((m for m in mandates if m.id==int(request.args["mandateId"])),None)
            except ValueError:return {"error":"Mandature invalide."},400
            if not selected:return {"error":"Mandature terminée introuvable."},404
        elif mandates:selected=mandates[0]
        return {"mandates":options,"stats":member_statistics(account.member_id,selected) if selected else None}

    def contribution_window(start_date,end_date):
        members=Member.query.all()
        rows=[]
        start_dt=datetime.combine(start_date,datetime.min.time());end_dt=datetime.combine(end_date+timedelta(days=1),datetime.min.time())
        for m in members:
            refs=Referral.query.filter(Referral.from_member_id==m.id,Referral.created_at>=start_dt,Referral.created_at<end_dt).count()
            business=float(db.session.query(db.func.coalesce(db.func.sum(BusinessThanks.amount),0)).filter(BusinessThanks.credited_member_id==m.id,BusinessThanks.business_date>=start_date,BusinessThanks.business_date<=end_date).scalar() or 0)
            visitors=NetworkVisitor.query.filter(NetworkVisitor.invited_by_member_id==m.id,NetworkVisitor.visit_date>=start_date,NetworkVisitor.visit_date<=end_date).count()
            otos=OneToOne.query.filter(db.or_(OneToOne.member_a_id==m.id,OneToOne.member_b_id==m.id),OneToOne.meeting_date>=start_date,OneToOne.meeting_date<=end_date).count()
            rows.append({"memberId":m.id,"member":f"{m.first_name} {m.last_name}","referrals":refs,"businessGenerated":business,"visitors":visitors,"oneToOnes":otos})
        def best(field):
            ranked=sorted(rows,key=lambda x:x[field],reverse=True)
            return ranked[0] if ranked and ranked[0][field]>0 else None
        return {"startDate":start_date.isoformat(),"endDate":end_date.isoformat(),"bestReferrals":best("referrals"),"bestBusiness":best("businessGenerated"),"bestVisitors":best("visitors"),"bestOneToOnes":best("oneToOnes")}

    @app.get("/api/network/contributors")
    def network_contributors():
        account,err=require_feature("ACTIVITY_SCORE")
        if err:return err
        today=date.today()
        period=request.args.get("period","week")
        if period=="month":
            start=today.replace(day=1)
            next_month=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
            end=min(today,next_month-timedelta(days=1))
        else:
            meetings=Meeting.query.filter(Meeting.date<=today,Meeting.type!="NO_MEETING").order_by(Meeting.date.desc()).limit(2).all()
            if len(meetings)>=2:
                end=meetings[0].date-timedelta(days=1);start=meetings[1].date
            elif meetings:
                start=meetings[0].date;end=today
            else:
                start=today-timedelta(days=7);end=today
        mandate=active_mandate()
        if mandate:start=max(start,mandate.start_date);end=min(end,mandate.end_date)
        else:start=today;end=today-timedelta(days=1)
        return contribution_window(start,end)

    @app.get("/api/network/hub-summary")
    def network_hub_summary():
        account,err=require_feature("ACTIVITY_SCORE")
        if err:return err
        mandate=active_mandate()
        if mandate:
            start,end=mandate.start_date,min(date.today(),mandate.end_date)
            name=mandate.name
        else:
            start=date.today();end=start-timedelta(days=1);name="Aucune mandature en cours"
        total=float(db.session.query(db.func.coalesce(db.func.sum(BusinessThanks.amount),0)).filter(BusinessThanks.business_date>=start,BusinessThanks.business_date<=end).scalar() or 0)
        referrals=Referral.query.filter(Referral.created_at>=datetime.combine(start,datetime.min.time()),Referral.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time())).count()
        won=Referral.query.filter(Referral.status=="WON",Referral.created_at>=datetime.combine(start,datetime.min.time()),Referral.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time())).count()
        return {"mandate":name,"startDate":start.isoformat(),"endDate":end.isoformat(),"businessTotal":total,"referrals":referrals,"wonReferrals":won}

    @app.get("/api/me/home")
    def member_home():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not official_member(account.member):return {"error":"Accueil réservé à l'espace Membres."},403
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        meetings=Meeting.query.filter(Meeting.date>=today,Meeting.type!="NO_MEETING",Meeting.status!="CANCELLED").order_by(Meeting.date,Meeting.start_time).all()
        # On the day itself, move on once the meeting start time has passed.
        now=datetime.now(ZoneInfo("Europe/Brussels"))
        meeting=next((m for m in meetings if m.date>today or not m.start_time or m.start_time>=now.time().replace(tzinfo=None)),None)
        next_payload=None
        if meeting:
            next_payload=meeting_details_payload(meeting)
        return {"memberStats":None,"groupStats":None,"offActivity":member_statistics(account.member_id,active_mandate()) if network_bridge_enabled(account) else None,"availableSubstitutes":[availability_payload(x) for x in visible_alumni_availability()],"nextMeeting":next_payload}

    @app.get("/api/network/leaderboard")
    def network_leaderboard():
        account,err=require_admin()
        if err:return err
        if not account.is_system_admin and not feature_enabled("NETWORK_MODULE"):return {"error":"Le module Réseau n'est pas activé."},403
        rows=[]
        for m in Member.query.order_by(Member.id).all():
            membership=active_membership_for(m.id)
            if not membership or membership.status not in {"ACTIVE","ONBOARDING","OFF"}:continue
            stats=member_statistics(m.id,active_mandate())
            rows.append({**stats,"company":m.company,"networkType":m.network_type or "OFFICIAL_BNI"})
        rows.sort(key=lambda x:(x["score"],x["businessGenerated"],x["referralsGiven"]),reverse=True)
        for i,x in enumerate(rows,1):x["rank"]=i
        return jsonify(rows)

    OFF_PLANS={
        "TRIAL":{"label":"Test 1 mois","price":100,"priceLabel":"100 € HTVA + petit déjeuner","durationDays":30,"rules":["Venir aux 4 jeudis du mois","Inviter 2 personnes","Donner 5 recommandations d'affaires","Réaliser 2 Tête-à-Tête"],"renewable":"Renouvelable une seule fois avant passage en annuel."},
        "ANNUAL":{"label":"Inscription 1 an","price":600,"priceLabel":"600 € HTVA + petit déjeuner","durationDays":365,"rules":["Respecter les règles de présence, d'absence et de suppléance","Encoder son activité avec les membres du Hub","Participer activement au développement du réseau"],"renewable":"Renouvelable annuellement."},
        "FREE":{"label":"Gratuit / test","price":0,"priceLabel":"Gratuit","durationDays":30,"rules":["Réservé principalement aux anciens membres","Permet de tester le réseau OFF avant arrêt complet ou inscription payante"],"renewable":"Durée et suite décidées avec le comité."}
    }

    def ensure_off_network_features():
        defaults={
            "NETWORK_MODULE":("Module Réseau","Afficher le menu Réseau aux membres autorisés."),
            "REFERRALS":("Recommandations","Encoder et suivre les recommandations entre membres."),
            "BUSINESS":("Business généré","Encoder les Merci pour le Business et le chiffre d'affaires généré."),
            "ONE_TO_ONE":("Tête-à-Tête","Encoder les rendez-vous individuels entre membres."),
            "VISITORS":("Invités","Encoder et suivre les invités amenés au groupe."),
            "ACTIVITY_SCORE":("Indice d'engagement","Calculer le score interne d'activité et les couleurs.")
        }
        for key,(label,desc) in defaults.items():
            row=db.session.get(FeatureFlag,key)
            if not row:
                row=FeatureFlag(key=key,label=label,description=desc,enabled=True)
                db.session.add(row)
            else:
                row.enabled=True

    def off_plan_enabled(code):
        mapping={"TRIAL":"OFF_PLAN_TRIAL","ANNUAL":"OFF_PLAN_ANNUAL","FREE":"OFF_PLAN_FREE"}
        return feature_enabled("OFF_MEMBERSHIP") and feature_enabled(mapping[code])

    def off_membership_payload(x):
        plan=OFF_PLANS.get(x.plan_code,{})
        return {"id":x.id,"memberId":x.member_id,"planCode":x.plan_code,"plan":plan,"status":x.status,"trialNumber":x.trial_number,"startsAt":x.starts_at.isoformat() if x.starts_at else None,"endsAt":x.ends_at.isoformat() if x.ends_at else None,"note":x.note,"createdAt":x.created_at.isoformat()}

    @app.get("/api/off-membership/me")
    def off_membership_me():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not feature_enabled("OFF_MEMBERSHIP"):return {"enabled":False,"offers":[],"plans":[],"autoFormerOffer":False}
        membership=Membership.query.filter_by(member_id=account.member_id).order_by(Membership.id.desc()).first()
        rows=OffMembership.query.filter_by(member_id=account.member_id).filter(OffMembership.status.in_(["OFFERED","INTERESTED","ACTIVE"])).order_by(OffMembership.created_at.desc()).all()
        plans=[{"code":code,**data} for code,data in OFF_PLANS.items() if off_plan_enabled(code)]
        auto_former=bool(membership and membership.status=="FORMER" and feature_enabled("OFF_FORMER_HOME_OFFER"))
        return {"enabled":True,"offers":[off_membership_payload(x) for x in rows],"plans":plans,"autoFormerOffer":auto_former,"isFormer":bool(membership and membership.status=="FORMER")}

    @app.post("/api/off-membership/<int:offer_id>/interest")
    def off_membership_interest(offer_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(OffMembership,offer_id)
        if not x or x.member_id!=account.member_id:return {"error":"Proposition introuvable."},404
        if x.status not in {"OFFERED","INTERESTED"}:return {"error":"Cette proposition n'est plus disponible."},400
        x.status="INTERESTED"
        notify(account.member_id,"OFF_MEMBERSHIP_INTEREST","Intérêt pour le réseau OFF","Votre intérêt a bien été enregistré. Le comité vous recontactera.","home")
        audit(account,"OFF_MEMBERSHIP_INTEREST","off_membership",x.id,x.plan_code)
        db.session.commit()
        return off_membership_payload(x)

    @app.post("/api/off-membership/request")
    def off_membership_request():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not feature_enabled("OFF_MEMBERSHIP"):return {"error":"Les adhésions OFF ne sont pas activées."},403
        data=request.get_json(silent=True) or {}
        code=(data.get("planCode") or "").strip().upper()
        if code not in OFF_PLANS or not off_plan_enabled(code):return {"error":"Cette formule n'est pas disponible."},400
        existing=OffMembership.query.filter_by(member_id=account.member_id,plan_code=code).filter(OffMembership.status.in_(["OFFERED","INTERESTED","ACTIVE"])).first()
        if existing:return off_membership_payload(existing)
        trial_count=OffMembership.query.filter_by(member_id=account.member_id,plan_code="TRIAL").filter(OffMembership.status.in_(["ACTIVE","EXPIRED"])).count()
        if code=="TRIAL" and trial_count>=2:return {"error":"La formule test 1 mois a déjà été utilisée deux fois. Une inscription annuelle est nécessaire."},400
        x=OffMembership(member_id=account.member_id,plan_code=code,status="INTERESTED",trial_number=(trial_count+1 if code=="TRIAL" else 1),note=(data.get("note") or "").strip() or None)
        db.session.add(x);db.session.flush()
        audit(account,"OFF_MEMBERSHIP_REQUEST","off_membership",x.id,code)
        db.session.commit()
        return off_membership_payload(x),201

    @app.post("/api/members/<int:member_id>/off-membership/offer")
    def system_offer_off_membership(member_id):
        account,err=require_system_admin()
        if err:return err
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        data=request.get_json(silent=True) or {}
        code=(data.get("planCode") or "").strip().upper()
        if code not in OFF_PLANS:return {"error":"Formule inconnue."},400
        if not feature_enabled("OFF_MEMBERSHIP") or not off_plan_enabled(code):return {"error":"Cette formule doit d'abord être activée dans Fonctionnalités."},400
        trial_count=OffMembership.query.filter_by(member_id=member_id,plan_code="TRIAL").filter(OffMembership.status.in_(["ACTIVE","EXPIRED"])).count()
        if code=="TRIAL" and trial_count>=2:return {"error":"Ce membre a déjà bénéficié de deux périodes test."},400
        x=OffMembership(member_id=member_id,plan_code=code,status="OFFERED",trial_number=(trial_count+1 if code=="TRIAL" else 1),offered_by_account_id=account.id,note=(data.get("note") or "").strip() or None)
        db.session.add(x);db.session.flush()
        notify(member_id,"OFF_MEMBERSHIP_OFFER","Invitation à découvrir le réseau OFF",f"Une proposition {OFF_PLANS[code]['label']} vous attend dans le Hub.","home")
        audit(account,"OFF_MEMBERSHIP_OFFERED","off_membership",x.id,f"member={member_id};plan={code}")
        db.session.commit()
        return off_membership_payload(x),201

    @app.get("/api/members/<int:member_id>/off-memberships")
    def system_member_off_memberships(member_id):
        _,err=require_system_admin()
        if err:return err
        rows=OffMembership.query.filter_by(member_id=member_id).order_by(OffMembership.created_at.desc()).all()
        return jsonify([off_membership_payload(x) for x in rows])

    @app.post("/api/off-membership/<int:offer_id>/activate")
    def system_activate_off_membership(offer_id):
        account,err=require_system_admin()
        if err:return err
        x=db.session.get(OffMembership,offer_id)
        if not x:return {"error":"Adhésion introuvable."},404
        data=request.get_json(silent=True) or {}
        start=date.today()
        if data.get("startsAt"):
            try:start=date.fromisoformat(data["startsAt"])
            except ValueError:return {"error":"Date de début invalide."},400
        duration=OFF_PLANS.get(x.plan_code,{}).get("durationDays",30)
        end=start+timedelta(days=duration-1)
        if data.get("endsAt"):
            try:end=date.fromisoformat(data["endsAt"])
            except ValueError:return {"error":"Date de fin invalide."},400
        member=db.session.get(Member,x.member_id)
        if official_member(member) and not member.alumni_requested_at:return {"error":"Le membre doit demander personnellement son passage chez les anciens."},400
        x.status="ACTIVE";x.starts_at=start;x.ends_at=end
        member.network_type="OFF";member.network_access_enabled=True
        ensure_off_network_features()
        membership=Membership.query.filter_by(member_id=member.id).order_by(Membership.id.desc()).first()
        if not membership:membership=Membership(member_id=member.id);db.session.add(membership)
        membership.status="OFF"
        current=MemberNetworkHistory.query.filter_by(member_id=member.id,end_date=None).order_by(MemberNetworkHistory.start_date.desc()).first()
        if current and current.network_type!="OFF":current.end_date=start-timedelta(days=1)
        if not current or current.network_type!="OFF":db.session.add(MemberNetworkHistory(member_id=member.id,network_type="OFF",start_date=start,changed_by_account_id=account.id))
        audit(account,"OFF_MEMBERSHIP_ACTIVATED","off_membership",x.id,f"{x.plan_code};{start}->{end}")
        db.session.commit()
        return off_membership_payload(x)

    @app.put("/api/members/<int:member_id>/network-access")
    def system_member_network_access(member_id):
        account,err=require_system_admin()
        if err:return err
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        data=request.get_json(silent=True) or {}
        member.network_access_enabled=bool(data.get("enabled"))
        audit(account,"MEMBER_NETWORK_ACCESS_UPDATED","member",member.id,f"enabled={member.network_access_enabled}")
        db.session.commit()
        return member_payload(member)

    @app.post("/api/members/<int:member_id>/password")
    def admin_set_member_password(member_id):
        account,auth_error=require_system_admin()
        if auth_error:return auth_error
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        target=member.user_account
        if not target:return {"error":"Ce membre ne possède pas encore de compte Hub actif."},400
        data=request.get_json(silent=True) or {}
        password=data.get("password") or ""
        if len(password)<10:return {"error":"Le mot de passe doit contenir au moins 10 caractères."},400
        target.password_hash=generate_password_hash(password)
        target.status="ACTIVE"
        target.password_reset_token=None
        target.password_reset_expires_at=None
        AuthSession.query.filter_by(account_id=target.id).delete()
        audit(account,"ADMIN_MEMBER_PASSWORD_CHANGED","user_account",target.id,f"memberId={member.id}")
        db.session.commit()
        return {"status":"ok","message":"Mot de passe modifié. Les anciennes sessions du membre ont été fermées."}

    @app.route("/api/members/<int:member_id>",methods=["GET","PATCH"])
    def member_detail(member_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        if request.method=="GET":return member_payload(member)
        data=request.get_json(silent=True) or {}
        for key,attr in [("firstName","first_name"),("lastName","last_name"),("company","company"),("activity","activity"),("phone","phone")]:
            if key in data:setattr(member,attr,(data.get(key) or "").strip() or None)
        if not member.first_name or not member.last_name:return {"error":"Prénom et nom obligatoires."},400
        if "email" in data:
            email=(data.get("email") or "").strip().lower() or None
            other=Member.query.filter(Member.id!=member.id,db.func.lower(Member.email)==email).first() if email else None
            if other:return {"error":"Cette adresse e-mail appartient déjà à un autre membre."},409
            if member.user_account and email and member.user_account.email.lower()!=email:
                used=UserAccount.query.filter(UserAccount.id!=member.user_account.id,db.func.lower(UserAccount.email)==email).first()
                if used:return {"error":"Cette adresse e-mail est déjà liée à un autre compte."},409
                member.user_account.email=email
            member.email=email
        membership=Membership.query.filter_by(member_id=member.id).order_by(Membership.id.desc()).first()
        if not membership:
            membership=Membership(member_id=member.id,status="ACTIVE");db.session.add(membership)
        if "status" in data:
            new_status=(data["status"] or "").strip().upper()
            if new_status not in {"ACTIVE","ONBOARDING","FORMER","OFF"}:return {"error":"Statut membre invalide."},400
            if new_status=="OFF" and official_member(member) and not member.alumni_requested_at:return {"error":"Le membre doit demander personnellement son passage chez les anciens."},400
            membership.status=new_status
            if new_status=="OFF":
                member.network_access_enabled=True
                ensure_off_network_features()
            if new_status=="OFF" and member.network_type!="OFF":
                current=MemberNetworkHistory.query.filter_by(member_id=member.id,end_date=None).order_by(MemberNetworkHistory.start_date.desc()).first()
                if current:current.end_date=date.today()-timedelta(days=1)
                member.network_type="OFF"
                db.session.add(MemberNetworkHistory(member_id=member.id,network_type="OFF",start_date=date.today()))

        if "startDate" in data:membership.start_date=date.fromisoformat(data["startDate"]) if data["startDate"] else None
        if "endDate" in data:membership.end_date=date.fromisoformat(data["endDate"]) if data["endDate"] else None
        db.session.commit()
        return member_payload(member)

    def parse_member_excel(file):
        wb=load_workbook(io.BytesIO(file.read()),read_only=True,data_only=True)
        ws=wb.active
        rows=list(ws.iter_rows(values_only=True))
        if not rows:return [],[],["Le fichier est vide."]
        aliases={"prenom":"firstName","prénom":"firstName","nom":"lastName","societe":"company","société":"company","entreprise":"company","activite":"activity","activité":"activity","email":"email","e-mail":"email","mail":"email","telephone":"phone","téléphone":"phone","gsm":"phone","date entree":"startDate","date d'entrée":"startDate","date entrée":"startDate","statut":"status"}
        import unicodedata
        def norm(v):
            s=str(v or "").strip().lower()
            return " ".join(s.split())
        headers=[norm(v) for v in rows[0]]
        mapping={i:aliases[h] for i,h in enumerate(headers) if h in aliases}
        if "firstName" not in mapping.values() or "lastName" not in mapping.values():
            return [],[],["Colonnes Prénom et Nom obligatoires."]
        preview=[];errors=[]
        for n,row in enumerate(rows[1:],start=2):
            data={}
            for i,key in mapping.items():
                if i>=len(row):continue
                v=row[i]
                if hasattr(v,"isoformat") and key=="startDate":v=v.date().isoformat() if hasattr(v,"date") else v.isoformat()
                data[key]=str(v).strip() if v is not None else ""
            if not data.get("firstName") and not data.get("lastName"):continue
            if not data.get("firstName") or not data.get("lastName"):
                errors.append(f"Ligne {n}: prénom ou nom manquant.");continue
            existing=Member.query.filter(db.func.lower(Member.first_name)==data["firstName"].lower(),db.func.lower(Member.last_name)==data["lastName"].lower()).first()
            data["row"]=n;data["action"]="UPDATE" if existing else "CREATE";data["existingId"]=existing.id if existing else None
            preview.append(data)
        return preview,[{"column":headers[i],"field":key} for i,key in mapping.items()],errors

    def validate_member_import(rows,kind):
        errors=[];seen=set();emails=set();resolved=[]
        for n,item in enumerate(rows,start=2):
            if not isinstance(item,dict):errors.append(f"Ligne {n}: données invalides.");continue
            first=str(item.get("firstName") or "").strip();last=str(item.get("lastName") or "").strip()
            label=f"Ligne {item.get('row',n)}"
            key=(first.casefold(),last.casefold());email=str(item.get("email") or "").strip().lower()
            if not first or not last:errors.append(f"{label}: prénom et nom obligatoires.");continue
            if key in seen or (email and email in emails):errors.append(f"{label}: doublon dans le fichier.");continue
            seen.add(key)
            if email:emails.add(email)
            matches=Member.query.filter(db.func.lower(Member.first_name)==first.lower(),db.func.lower(Member.last_name)==last.lower()).all()
            if len(matches)>1:errors.append(f"{label}: plusieurs homonymes, modifier leur fiche individuellement.");continue
            member=matches[0] if matches else None
            if member and ((kind=="ALUMNI" and official_member(member)) or (kind=="BNI" and alumni_member(member))):
                errors.append(f"{label}: {first} {last} appartient à l’autre espace. Utiliser le parcours de basculement.");continue
            if email:
                other=Member.query.filter(db.func.lower(Member.email)==email).first()
                account=UserAccount.query.filter(db.func.lower(UserAccount.email)==email).first()
                if (other and (not member or other.id!=member.id)) or (account and (not member or account.member_id!=member.id)):
                    errors.append(f"{label}: e-mail déjà utilisé par un autre membre.");continue
                if member and member.user_account and member.user_account.email.lower()!=email:
                    errors.append(f"{label}: modifier l’e-mail du compte depuis sa fiche membre.");continue
            if item.get("startDate"):
                try:date.fromisoformat(str(item["startDate"])[:10])
                except ValueError:errors.append(f"{label}: date d’entrée invalide.");continue
            expected={"OFF"} if kind=="ALUMNI" else {"ACTIVE","ONBOARDING"}
            if item.get("status") and str(item["status"]).upper() not in expected:
                errors.append(f"{label}: statut incompatible avec l’espace choisi.");continue
            resolved.append(({**item,"firstName":first,"lastName":last,"email":email,"action":"UPDATE" if member else "CREATE","existingId":member.id if member else None},member))
        return resolved,errors

    @app.post("/api/members/import/preview")
    def import_members_preview():
        _,auth_error=require_system_admin()
        if auth_error:return auth_error
        kind=request.form.get("memberType","BNI")
        if kind not in {"BNI","ALUMNI"}:return {"error":"Type de membre invalide."},400
        file=request.files.get("file")
        if not file or not file.filename.lower().endswith(".xlsx"):return {"error":"Fichier .xlsx requis."},400
        try: preview,mapping,errors=parse_member_excel(file)
        except Exception:return {"error":"Impossible de lire ce fichier Excel."},400
        resolved,validation_errors=validate_member_import(preview,kind)
        errors+=validation_errors
        preview=[item for item,_ in resolved]
        return {"memberType":kind,"rows":preview,"mapping":mapping,"errors":errors,"summary":{"total":len(preview),"create":sum(x["action"]=="CREATE" for x in preview),"update":sum(x["action"]=="UPDATE" for x in preview)}}

    @app.post("/api/members/import/confirm")
    def import_members_confirm():
        _,auth_error=require_system_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        kind=data.get("memberType","BNI")
        if kind not in {"BNI","ALUMNI"}:return {"error":"Type de membre invalide."},400
        rows=data.get("rows")
        if not isinstance(rows,list) or not rows:return {"error":"Aucune ligne à importer."},400
        resolved,errors=validate_member_import(rows,kind)
        if errors:return {"error":" ".join(errors),"errors":errors},400
        created=updated=0
        for item,member in resolved:
            if member:updated+=1
            else:
                member=Member(first_name=item["firstName"],last_name=item["lastName"],alumni_bridge_enabled=False)
                db.session.add(member);db.session.flush();created+=1
            for key,attr in [("company","company"),("activity","activity"),("email","email"),("phone","phone")]:
                if item.get(key):setattr(member,attr,str(item[key]).strip())
            membership=active_membership_for(member.id)
            target="OFF" if kind=="ALUMNI" else "ACTIVE"
            if not membership or membership.status=="FORMER":
                membership=Membership(member_id=member.id,status=target,start_date=date.today());db.session.add(membership)
            if kind=="ALUMNI":membership.status="OFF"
            elif item.get("status"):membership.status=str(item["status"]).upper()
            if item.get("startDate"):membership.start_date=date.fromisoformat(str(item["startDate"])[:10])
            network="OFF" if kind=="ALUMNI" else "OFFICIAL_BNI"
            current=MemberNetworkHistory.query.filter_by(member_id=member.id,end_date=None).order_by(MemberNetworkHistory.id.desc()).first()
            if not current or current.network_type!=network:
                if current:current.end_date=date.today()-timedelta(days=1)
                db.session.add(MemberNetworkHistory(member_id=member.id,network_type=network,start_date=date.today()))
            member.network_type=network
            if kind=="ALUMNI":member.network_access_enabled=True;member.alumni_bridge_enabled=False
        account,_=bearer_account()
        log=ImportLog(account_id=account.id,filename=(("Anciens · " if kind=="ALUMNI" else "Membres BNI · ")+(data.get("filename") or "import.xlsx"))[:255],created_count=created,updated_count=updated,error_count=0)
        db.session.add(log)
        db.session.commit()
        return {"status":"ok","created":created,"updated":updated}

    @app.get("/api/members/import/history")
    def import_members_history():
        _,auth_error=require_system_admin()
        if auth_error:return auth_error
        rows=ImportLog.query.order_by(ImportLog.created_at.desc()).limit(50).all()
        return jsonify([{"id":x.id,"filename":x.filename,"created":x.created_count,"updated":x.updated_count,"errors":x.error_count,"createdAt":x.created_at.isoformat(),"by":f"{x.account.member.first_name} {x.account.member.last_name}"} for x in rows])

    @app.get("/api/members/export")
    def export_members():
        _,auth_error=require_system_admin()
        if auth_error:return auth_error
        wb=Workbook();ws=wb.active;ws.title="Membres"
        ws.append(["Prénom","Nom","Société","Activité","Email","Téléphone","Date entrée","Date sortie","Statut","Accès Hub"])
        for m in Member.query.order_by(Member.last_name,Member.first_name).all():
            membership=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
            ws.append([m.first_name,m.last_name,m.company or "",m.activity or "",m.email or "",m.phone or "",membership.start_date if membership else None,membership.end_date if membership else None,membership.status if membership else "",m.user_account.status if m.user_account else "NO_ACCOUNT"])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width=min(max(12,max(len(str(cell.value or "")) for cell in col)+2),40)
        out=io.BytesIO();wb.save(out);out.seek(0)
        return send_file(out,as_attachment=True,download_name=f"HUB-Soignies-Membres-{date.today().isoformat()}.xlsx",mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def invitation_message(member,activation_url,copy_email):
        base=HUB_APP_URL
        sender=os.getenv("SMTP_FROM","").strip()
        msg=EmailMessage()
        space="HUB Anciens" if alumni_member(member) else "HUB Soignies"
        invitation_text="Gardez le contact avec les anciens et échangez recommandations, MPB et TAT. Les échanges avec les membres actifs sont limités à ceux qui ont activé leur liaison personnelle." if alumni_member(member) else "Retrouvez les informations et la vie du groupe dans votre espace Membres."
        msg["Subject"]=space+" — votre invitation"
        msg["From"]=sender;msg["To"]=member.email or member.user_account.email
        msg.set_content(f"""Bonjour {member.first_name},

Vous êtes invité(e) à découvrir {space}.

{invitation_text}

Activez votre accès avec ce lien (valable 48 heures) :
{activation_url}

COMMENT AJOUTER HUB À L’ÉCRAN D’ACCUEIL DE VOTRE GSM

1. Activez d’abord votre compte avec le lien ci-dessus et choisissez votre mot de passe.
2. Ouvrez ensuite l’adresse habituelle du HUB :
{base}/
Utilisez cette adresse pour le raccourci, et non le lien personnel d’activation qui expire après 48 heures.

Sur iPhone (Safari) :
- Ouvrez {base}/ dans Safari.
- Touchez Partager (le carré avec une flèche vers le haut ; selon la version, passez par le menu Plus).
- Choisissez « Sur l’écran d’accueil » ou « Ajouter à l’écran d’accueil ».
- Si proposé, activez « Ouvrir comme app web », puis touchez « Ajouter ».

Sur Android (Google Chrome) :
- Ouvrez {base}/ dans Chrome.
- Touchez le menu avec les trois points, puis « Installer et créer un raccourci » ou « Ajouter à l’écran d’accueil », selon votre version.
- Choisissez « Créer un raccourci », puis « Ajouter » (ou confirmez « Installer » si cette option est proposée).

L’icône HUB vous permettra de retrouver votre espace. Connectez-vous avec l’adresse e-mail qui a reçu cette invitation et votre nouveau mot de passe.
Si le lien s’ouvre dans le navigateur intégré de votre messagerie, copiez l’adresse du HUB dans Safari (iPhone) ou Chrome (Android).

À bientôt sur HUB Soignies.""")
        if alumni_member(member):
            msg.replace_header("Subject","Et si on gardait le lien ? Découvre le HUB des anciens")
            msg["Cc"]="hub@bim-soignies.be"
            msg.set_content(f"""Bonjour {member.first_name},

Tu as fait partie du BNI de Soignies. Nous y avons partagé des rencontres, du business et de bons moments. Pourquoi perdre ce lien après ton départ du groupe ?

Nous avons développé HUB – BIM, une webapp pour continuer à échanger entre anciens, ainsi qu’avec les membres actifs qui ont choisi d’activer cette liaison.

Tu peux y transmettre une recommandation, enregistrer un tête-à-tête (TAT), un Merci pour le Business (MPB), mais aussi devenir un SUPER SUPPLÉANT !

Le principe : lorsqu’un membre signale un besoin de remplacement, les anciens reçoivent une notification. Si tu es disponible, tu peux accepter. Le premier qui confirme s’engage à assurer la suppléance.

Aucune obligation de participer régulièrement : chacun échange à son rythme. C’est une première expérience pour garder le contact et voir ce que nous pourrons construire ensemble, dans l’esprit de confiance et d’entraide que tu connais.

ENVIE D’ESSAYER ?

Commence par activer ton compte grâce à ton lien personnel d’invitation et choisis ton mot de passe :
{activation_url}

Ce lien est valable 48 heures.

Ajoute ensuite le HUB à l’écran d’accueil de ton téléphone :

Sur iPhone (Safari)
1. Ouvre {base}/ dans Safari.
2. Appuie sur Partager — le carré avec une flèche vers le haut, éventuellement accessible depuis le menu.
3. Choisis Sur l’écran d’accueil.
4. Si l’option apparaît, active Ouvrir comme app web, puis appuie sur Ajouter.

Sur Android (Google Chrome)
1. Ouvre {base}/ dans Google Chrome.
2. Appuie sur les trois points du menu.
3. Choisis Ajouter à l’écran d’accueil ou Installer et créer un raccourci, selon ta version.
4. Confirme avec Ajouter ou Installer.

Utilise bien l’adresse habituelle du HUB pour créer l’icône, et non le lien personnel d’activation temporaire.

Tu peux ensuite ouvrir le HUB depuis son icône, te connecter et commencer à découvrir les échanges et les suppléances proposées.

Une question ? Écris-nous à hub@bim-soignies.be, ou contacte Xavier au +32 473 531 656.

Au plaisir de te retrouver !

Le groupe HUB – BIM
""")
        if copy_email and not msg.get("Cc"):msg["Cc"]=copy_email
        return msg

    def invitation_delivery(msg,recipients,member_id,actor):
        from copy import deepcopy
        from email.utils import make_msgid,formatdate
        results={kind:{"accepted":False,"error":None} for kind,_ in recipients}
        host=os.getenv("SMTP_HOST","").strip();sender=os.getenv("SMTP_FROM","").strip()
        if not host or not sender:
            for item in results.values():item["error"]={"code":"MAIL_NOT_CONFIGURED","message":"Le serveur ou l’expéditeur mail du HUB n’est pas configuré."}
        else:
            smtp=None
            try:
                port=int(os.getenv("SMTP_PORT","587"));use_ssl=os.getenv("SMTP_SSL","false").lower() in {"1","true","yes"}
                smtp=smtplib.SMTP_SSL(host,port,timeout=15) if use_ssl else smtplib.SMTP(host,port,timeout=15)
                if not use_ssl and os.getenv("SMTP_STARTTLS","true").lower() in {"1","true","yes"}:smtp.starttls()
                username=os.getenv("SMTP_USER","").strip()
                if username:smtp.login(username,os.getenv("SMTP_PASSWORD",""))
                for kind,recipient in recipients:
                    outgoing=deepcopy(msg)
                    if kind=="copy":
                        outgoing.replace_header("To",recipient)
                        if outgoing.get("Cc"):del outgoing["Cc"]
                        outgoing.replace_header("Subject","Copie HUB — "+str(msg["Subject"]))
                    if outgoing.get("Message-ID"):del outgoing["Message-ID"]
                    outgoing["Message-ID"]=make_msgid(domain="bim-soignies.be")
                    if not outgoing.get("Date"):outgoing["Date"]=formatdate(localtime=False)
                    try:
                        refused=smtp.send_message(outgoing,to_addrs=[recipient])
                        if refused:raise smtplib.SMTPRecipientsRefused(refused)
                        results[kind]["accepted"]=True
                    except Exception as exc:results[kind]["error"]=invitation_smtp_error(exc)
            except Exception as exc:
                error=invitation_smtp_error(exc)
                for item in results.values():
                    if not item["accepted"] and not item["error"]:item["error"]=error
            finally:
                if smtp:
                    try:smtp.quit()
                    except Exception:pass
        for kind,result in results.items():
            error=result["error"] or {}
            audit(actor,"INVITATION_EMAIL_DELIVERY","member",member_id,f"recipient_kind={kind};smtp_accepted={result['accepted']};error_code={error.get('code','')};smtp_code={error.get('smtpCode','')}")
            if error:app.logger.warning("HUB invitation failed member_id=%s recipient_kind=%s error_code=%s smtp_code=%s",member_id,kind,error.get("code"),error.get("smtpCode"))
            if error.get("detail"):app.logger.warning("HUB copy refusal detail: %s",error["detail"])
        db.session.commit()
        return results

    def invitation_smtp_error(exc):
        import socket
        if isinstance(exc,smtplib.SMTPRecipientsRefused):
            codes=[int(v[0]) for v in exc.recipients.values()]
            reply=next(iter(exc.recipients.values()))[1] if exc.recipients else ""
            if isinstance(reply,bytes):reply=reply.decode("utf-8","replace")
            return {"code":"RECIPIENT_REFUSED","smtpCode":codes[0] if codes else None,"message":"Le serveur mail a refusé l’adresse destinataire.","detail":" ".join(str(reply).split())[:240]}
        if isinstance(exc,smtplib.SMTPAuthenticationError):return {"code":"SMTP_AUTH_FAILED","smtpCode":int(exc.smtp_code),"message":"L’authentification auprès du serveur mail a échoué."}
        if isinstance(exc,smtplib.SMTPSenderRefused):return {"code":"SENDER_REFUSED","smtpCode":int(exc.smtp_code),"message":"Le serveur mail a refusé l’expéditeur configuré."}
        if isinstance(exc,smtplib.SMTPResponseException):return {"code":"SMTP_REJECTED","smtpCode":int(exc.smtp_code),"message":"Le serveur mail a refusé le message."}
        if isinstance(exc,(OSError,socket.timeout,smtplib.SMTPServerDisconnected)):return {"code":"SMTP_CONNECTION_FAILED","message":"La connexion au serveur mail a échoué ou a été interrompue."}
        return {"code":"MAIL_DELIVERY_FAILED","message":"L’envoi du mail a échoué."}

    @app.post("/api/system/mail-test")
    def hub_mail_test():
        actor,err=require_system_admin()
        if err:return err
        msg=EmailMessage();msg["From"]=os.getenv("SMTP_FROM","").strip();msg["To"]="hub@bim-soignies.be";msg["Subject"]="Test de réception HUB – BIM"
        msg.set_content("Ce message teste uniquement la réception des copies sur hub@bim-soignies.be. Aucune invitation n’a été envoyée ou modifiée pour un membre.")
        result=invitation_delivery(msg,[("copy","hub@bim-soignies.be")],actor.member_id,actor)["copy"]
        return {"copyEmail":"hub@bim-soignies.be","copyEmailSent":result["accepted"],"copyEmailError":result["error"],"mailTest":True}

    @app.post("/api/members/<int:member_id>/invite-copy")
    def resend_invitation_copy(member_id):
        actor,err=require_admin()
        if err:return err
        member=db.session.get(Member,member_id)
        if not member:return {"error":"Membre introuvable."},404
        membership=active_membership_for(member.id)
        if not alumni_member(member) and not (membership and membership.status=="FORMER"):return {"error":"La copie HUB concerne les invitations des anciens."},400
        account=member.user_account
        if not account or account.status!="INVITED" or not account.invitation_token or not account.invitation_expires_at or account.invitation_expires_at<=datetime.utcnow():return {"error":"L’invitation n’est plus en attente ou son lien a expiré. Aucune copie envoyée."},409
        url=f"{HUB_APP_URL}/?activate={account.invitation_token}"
        message=invitation_message(member,url,"hub@bim-soignies.be")
        result=invitation_delivery(message,[("copy","hub@bim-soignies.be")],member.id,actor)["copy"]
        return {"copyEmail":"hub@bim-soignies.be","copyEmailSent":result["accepted"],"copyEmailError":result["error"],"activationUrl":url,"expiresInHours":max(1,int((account.invitation_expires_at-datetime.utcnow()).total_seconds()/3600))}

    @app.post("/api/members/<int:member_id>/invite")
    def invite_member(member_id):
        inviter,auth_error=require_admin()
        if auth_error:return auth_error
        member=db.session.get(Member,member_id)
        if not member:
            return {"error":"Membre introuvable."},404
        if not member.email:
            return {"error":"Une adresse e-mail est nécessaire pour créer l'accès."},400
        existing=UserAccount.query.filter(db.func.lower(UserAccount.email)==member.email.lower()).first()
        if existing and existing.member_id!=member.id:
            return {"error":"Cette adresse e-mail est déjà liée à un autre compte."},409
        account=member.user_account or UserAccount(member_id=member.id,email=member.email.lower())
        account.email=member.email.lower()
        account.status="INVITED"
        account.invitation_token=secrets.token_urlsafe(32)
        account.invitation_expires_at=datetime.utcnow()+timedelta(hours=48)
        if not account.id: db.session.add(account)
        db.session.commit()
        base=HUB_APP_URL
        activation_url=f"{base}/?activate={account.invitation_token}"
        email_sent=False
        membership=active_membership_for(member.id)
        copy_email="hub@bim-soignies.be" if alumni_member(member) or (membership and membership.status=="FORMER") else None
        copy_sent=False if copy_email else None
        message=invitation_message(member,activation_url,copy_email)
        deliveries=invitation_delivery(message,[("member",member.email)]+([("copy",copy_email)] if copy_email else []),member.id,inviter)
        primary=deliveries["member"];copied=deliveries.get("copy",{})
        return {"status":"INVITED","activationUrl":activation_url,"expiresInHours":48,"emailSent":primary["accepted"],"emailError":primary["error"],"copyEmail":copy_email,"copyEmailSent":copied.get("accepted"),"copyEmailError":copied.get("error")}

    @app.post("/api/auth/forgot-password")
    def forgot_password():
        data=request.get_json(silent=True) or {}
        email=(data.get("email") or "").strip().lower()
        account=UserAccount.query.filter(db.func.lower(UserAccount.email)==email).first() if email else None
        if account and account.status=="ACTIVE":
            account.password_reset_token=secrets.token_urlsafe(32)
            account.password_reset_expires_at=datetime.utcnow()+timedelta(hours=1)
            db.session.commit()
            base=HUB_APP_URL
            reset_url=f"{base}/?reset={account.password_reset_token}"
            host=os.getenv("SMTP_HOST","").strip();sender=os.getenv("SMTP_FROM","").strip()
            if host and sender:
                msg=EmailMessage()
                msg["Subject"]="HUB Soignies — réinitialisation du mot de passe"
                msg["From"]=sender;msg["To"]=account.email
                msg.set_content(f"""Bonjour {account.member.first_name},

Une demande de réinitialisation de votre mot de passe HUB Soignies a été reçue.

Choisissez un nouveau mot de passe avec ce lien (valable 1 heure) :
{reset_url}

Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet e-mail.""")
                port=int(os.getenv("SMTP_PORT","587"));user=os.getenv("SMTP_USER","").strip();password=os.getenv("SMTP_PASSWORD","")
                use_ssl=os.getenv("SMTP_SSL","false").lower() in {"1","true","yes"}
                smtp=(smtplib.SMTP_SSL(host,port,timeout=15) if use_ssl else smtplib.SMTP(host,port,timeout=15))
                try:
                    if not use_ssl and os.getenv("SMTP_STARTTLS","true").lower() in {"1","true","yes"}:smtp.starttls()
                    if user:smtp.login(user,password)
                    smtp.send_message(msg)
                except Exception as exc:
                    app.logger.exception("Password reset email delivery failed for account %s: %s",account.id,exc)
                finally:
                    try:smtp.quit()
                    except Exception:pass
        return {"status":"ok","message":"Si cette adresse correspond à un compte actif, un e-mail de réinitialisation a été envoyé."}

    @app.post("/api/auth/reset-password")
    def reset_password():
        data=request.get_json(silent=True) or {}
        token=(data.get("token") or "").strip()
        password=data.get("password") or ""
        if len(password)<10:return {"error":"Le mot de passe doit contenir au moins 10 caractères."},400
        account=UserAccount.query.filter_by(password_reset_token=token).first()
        if not account or not account.password_reset_expires_at or account.password_reset_expires_at<datetime.utcnow():
            return {"error":"Lien de réinitialisation invalide ou expiré."},400
        account.password_hash=generate_password_hash(password)
        account.password_reset_token=None
        account.password_reset_expires_at=None
        AuthSession.query.filter_by(account_id=account.id).delete()
        audit(account,"PASSWORD_RESET","user_account",account.id)
        db.session.commit()
        return {"status":"ok","message":"Votre mot de passe a été modifié."}

    @app.post("/api/auth/activate")
    def activate():
        data=request.get_json(silent=True) or {}
        token=(data.get("token") or "").strip()
        password=data.get("password") or ""
        if len(password)<10:
            return {"error":"Le mot de passe doit contenir au moins 10 caractères."},400
        account=UserAccount.query.filter_by(invitation_token=token).first()
        if not account or not account.invitation_expires_at or account.invitation_expires_at<datetime.utcnow():
            return {"error":"Lien d'activation invalide ou expiré."},400
        account.password_hash=generate_password_hash(password)
        account.status="ACTIVE"
        account.activated_at=datetime.utcnow()
        account.invitation_token=None
        account.invitation_expires_at=None
        db.session.commit()
        return {"status":"ACTIVE","message":"Compte activé."}

    def account_payload(account):
        today=date.today()
        active_mandates=Mandate.query.filter(Mandate.start_date<=today,Mandate.end_date>=today).all()
        mandate_ids=[m.id for m in active_mandates]
        roles=[]
        if mandate_ids and official_member(account.member):
            assignments=RoleAssignment.query.filter(RoleAssignment.member_id==account.member_id,RoleAssignment.mandate_id.in_(mandate_ids),RoleAssignment.status=="ACTIVE").all()
            role_ids=[a.role_id for a in assignments]
            if role_ids: roles=[r.name for r in Role.query.filter(Role.id.in_(role_ids)).all()]
        admin=bool(account.is_system_admin or any(r.lower().strip() in {"président","president","vice-président","vice president","vice-president","secrétaire trésorier","secretaire tresorier","secrétaire-trésorier","secretaire-tresorier","trésorier","tresorier"} for r in roles))
        return {"id":account.member.id,"firstName":account.member.first_name,"lastName":account.member.last_name,"email":account.email,"roles":roles,"isAdmin":admin,"isSystemAdmin":bool(account.is_system_admin),"networkType":account.member.network_type or "OFFICIAL_BNI","networkAccessEnabled":bool(full_network_enabled(account)),"networkModuleEnabled":bool(full_network_enabled(account)),"networkBridgeEnabled":bool(network_bridge_enabled(account)),"alumniBridgeEnabled":bool(account.member.alumni_bridge_enabled),"environment":"ALUMNI" if alumni_member(account.member) else "MEMBERS" if official_member(account.member) else "INACTIVE"}

    def bearer_account():
        header=request.headers.get("Authorization","")
        if not header.startswith("Bearer "): return None,None
        raw=header[7:].strip()
        import hashlib
        hashed=hashlib.sha256(raw.encode()).hexdigest()
        session=AuthSession.query.filter_by(token_hash=hashed).first()
        if not session or session.expires_at<datetime.utcnow():
            if session:
                db.session.delete(session);db.session.commit()
            return None,None
        if session.account.status!="ACTIVE":return None,None
        if session.support_actor_id:
            if session.account.is_system_admin:return None,None
            actor=db.session.get(UserAccount,session.support_actor_id)
            parent=db.session.get(AuthSession,session.support_parent_id)
            if not actor or not actor.is_system_admin or actor.status!="ACTIVE" or not parent or parent.account_id!=actor.id or parent.support_actor_id or parent.expires_at<datetime.utcnow():return None,None
        return session.account,session

    @app.post("/api/system/support-sessions")
    def start_support_session():
        actor,err=require_system_admin()
        if err:return err
        _,parent=bearer_account()
        try:member_id=int((request.get_json(silent=True) or {}).get("memberId"))
        except (ValueError,TypeError):return {"error":"Membre invalide."},400
        member=db.session.get(Member,member_id)
        target=member.user_account if member else None
        if not member:return {"error":"Membre introuvable."},404
        if not target or target.status!="ACTIVE":return {"error":"Le membre doit avoir activé son compte pour ouvrir son interface réelle."},400
        if target.is_system_admin:return {"error":"Utilisez votre vue membre pour un compte super administrateur."},403
        raw=secrets.token_urlsafe(48)
        import hashlib
        session=AuthSession(account_id=target.id,token_hash=hashlib.sha256(raw.encode()).hexdigest(),expires_at=min(parent.expires_at,datetime.utcnow()+timedelta(minutes=30)),support_actor_id=actor.id,support_parent_id=parent.id)
        db.session.add(session);db.session.flush()
        audit(actor,"SUPPORT_SESSION_STARTED","member",member.id,f"session_id={session.id};read_only=true;expires_at={session.expires_at.isoformat()}")
        db.session.commit()
        return {"token":raw,"expiresAt":session.expires_at.isoformat()+"Z","memberId":member.id,"readOnly":True},201

    @app.post("/api/system/support-sessions/stop")
    def stop_support_session():
        _,session=bearer_account()
        if not session or not session.support_actor_id:return {"error":"Session assistance introuvable."},401
        actor=db.session.get(UserAccount,session.support_actor_id)
        audit(actor,"SUPPORT_SESSION_STOPPED","member",session.account.member_id,f"session_id={session.id}")
        db.session.delete(session);db.session.commit()
        return {"status":"ok"}

    @app.post("/api/auth/login")
    def login():
        data=request.get_json(silent=True) or {}
        email=(data.get("email") or "").strip().lower()
        account=UserAccount.query.filter(db.func.lower(UserAccount.email)==email).first()
        if not account or account.status!="ACTIVE" or not account.password_hash or not check_password_hash(account.password_hash,data.get("password") or ""):
            return {"error":"Identifiants incorrects."},401
        raw=secrets.token_urlsafe(48)
        import hashlib
        session=AuthSession(account_id=account.id,token_hash=hashlib.sha256(raw.encode()).hexdigest(),expires_at=datetime.utcnow()+timedelta(days=SESSION_DAYS))
        db.session.add(session);db.session.commit()
        return {"token":raw,"expiresInDays":SESSION_DAYS,"member":account_payload(account)}

    @app.get("/api/auth/me")
    def me():
        account,session=bearer_account()
        if not account:return {"error":"Session invalide ou expirée."},401
        now=datetime.utcnow()
        # Extend only here, before application writes; existing valid sessions are upgraded too.
        if not session.support_actor_id and session.expires_at<now+timedelta(days=SESSION_DAYS-1):
            session.expires_at=now+timedelta(days=SESSION_DAYS)
            db.session.commit()
        payload=account_payload(account)
        if session.support_actor_id:payload={**payload,"isAdmin":False,"isSystemAdmin":False,"supportSession":True,"supportReadOnly":True,"supportExpiresAt":session.expires_at.isoformat()+"Z"}
        return {"member":payload,"expiresInDays":SESSION_DAYS if not session.support_actor_id else None,"expiresAt":session.expires_at.isoformat()+"Z"}

    @app.post("/api/auth/logout")
    def logout():
        _,session=bearer_account()
        if session:
            db.session.delete(session);db.session.commit()
        return {"status":"ok"}

    @app.post("/api/system/bootstrap-xavier")
    def bootstrap_xavier():
        key=request.headers.get("X-Bootstrap-Key","")
        if not key or not secrets.compare_digest(key,os.getenv("BOOTSTRAP_KEY","disabled")):
            return {"error":"Forbidden"},403
        candidates=Member.query.filter(db.func.lower(Member.first_name)=="xavier",db.func.lower(Member.last_name)=="renaud").all()
        active=None
        for m in candidates:
            if m.user_account and m.user_account.status=="ACTIVE" and m.user_account.password_hash:
                active=m;break
        if not active:
            return {"error":"Aucun compte Xavier Renaud actif trouvé."},404
        active.user_account.is_system_admin=True
        membership=Membership.query.filter_by(member_id=active.id).order_by(Membership.id.asc()).first()
        if not membership:
            membership=Membership(member_id=active.id,status="ACTIVE");db.session.add(membership)
        membership.start_date=date(2017,4,1)
        membership.end_date=None
        membership.status="ACTIVE"
        mandate=Mandate.query.filter_by(name="Octobre 2026 - Mars 2027").first()
        if not mandate:
            mandate=Mandate(name="Octobre 2026 - Mars 2027",start_date=date(2026,10,1),end_date=date(2027,3,31),status="PREPARATION");db.session.add(mandate);db.session.flush()
        role=Role.query.filter(db.func.lower(Role.name)=="président").first()
        if not role:
            role=Role(name="Président");db.session.add(role);db.session.flush()
        assignment=RoleAssignment.query.filter_by(mandate_id=mandate.id,role_id=role.id,member_id=active.id).first()
        if not assignment:
            assignment=RoleAssignment(mandate_id=mandate.id,role_id=role.id,member_id=active.id,status="ACTIVE");db.session.add(assignment)
        db.session.commit()
        return {"status":"ok","memberId":active.id,"systemAdmin":True,"membershipStart":"2017-04-01","mandate":mandate.name,"role":"Président","roleStarts":"2026-10-01","duplicateCandidates":len(candidates)}

    def mandate_payload(m):
        assignments=RoleAssignment.query.filter_by(mandate_id=m.id,status="ACTIVE").all()
        role_ids=list({a.role_id for a in assignments})
        roles={r.id:r for r in Role.query.filter(Role.id.in_(role_ids)).all()} if role_ids else {}
        member_ids=list({a.member_id for a in assignments})
        members={x.id:x for x in Member.query.filter(Member.id.in_(member_ids)).all()} if member_ids else {}
        return {"id":m.id,"name":m.name,"startDate":m.start_date.isoformat(),"endDate":m.end_date.isoformat(),"status":m.status,
                "committee":[{"assignmentId":a.id,"roleId":a.role_id,"role":roles[a.role_id].name if a.role_id in roles else "—","memberId":a.member_id,
                "member":f"{members[a.member_id].first_name} {members[a.member_id].last_name}" if a.member_id in members else "—"} for a in assignments]}

    def handover_payload(x):
        role=db.session.get(Role,x.role_id);fm=db.session.get(Mandate,x.from_mandate_id);tm=db.session.get(Mandate,x.to_mandate_id)
        return {"id":x.id,"title":x.title,"notes":x.notes,"roleId":x.role_id,"role":role.name if role else "—","fromMandate":fm.name if fm else "—","toMandate":tm.name if tm else "—","outgoingConfirmed":bool(x.outgoing_confirmed_at),"incomingConfirmed":bool(x.incoming_confirmed_at),"complete":bool(x.outgoing_confirmed_at and x.incoming_confirmed_at)}

    @app.post("/api/handovers/generate")
    def handovers_generate():
        _,err=require_admin()
        if err:return err
        d=request.get_json(silent=True) or {}
        try:from_id=int(d["fromMandateId"]);to_id=int(d["toMandateId"])
        except (KeyError,TypeError,ValueError):return {"error":"Mandatures obligatoires."},400
        incoming=RoleAssignment.query.filter_by(mandate_id=to_id,status="ACTIVE").all()
        created=0
        defaults=["Points clés et dossiers en cours","Procédures et échéances","Ressources et documents","Plateformes, accès et renouvellements"]
        for a in incoming:
            outgoing=RoleAssignment.query.filter_by(mandate_id=from_id,role_id=a.role_id,status="ACTIVE").first()
            if not outgoing:continue
            for title in defaults:
                exists=HandoverItem.query.filter_by(from_mandate_id=from_id,to_mandate_id=to_id,role_id=a.role_id,title=title).first()
                if not exists:
                    db.session.add(HandoverItem(from_mandate_id=from_id,to_mandate_id=to_id,role_id=a.role_id,title=title));created+=1
        db.session.commit()
        return {"created":created,"items":[handover_payload(x) for x in HandoverItem.query.filter_by(from_mandate_id=from_id,to_mandate_id=to_id).order_by(HandoverItem.role_id,HandoverItem.id).all()]}

    @app.get("/api/handovers")
    def handovers_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if account.is_system_admin:return jsonify([handover_payload(x) for x in HandoverItem.query.order_by(HandoverItem.id.desc()).all()])
        role_ids=current_role_ids(account)
        rows=HandoverItem.query.filter(HandoverItem.role_id.in_(role_ids)).order_by(HandoverItem.id.desc()).all() if role_ids else []
        return jsonify([handover_payload(x) for x in rows])

    @app.get("/api/me/handovers")
    def my_handovers():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=HandoverItem.query.order_by(HandoverItem.id.desc()).all()
        out=[]
        for x in rows:
            outgoing=RoleAssignment.query.filter_by(mandate_id=x.from_mandate_id,role_id=x.role_id,member_id=account.member_id,status="ACTIVE").first()
            incoming=RoleAssignment.query.filter_by(mandate_id=x.to_mandate_id,role_id=x.role_id,member_id=account.member_id,status="ACTIVE").first()
            if outgoing or incoming:
                p=handover_payload(x);p["mySide"]="outgoing" if outgoing else "incoming";out.append(p)
        return jsonify(out)

    @app.post("/api/handovers")
    def handovers_create():
        _,err=require_admin()
        if err:return err
        d=request.get_json(silent=True) or {}
        try:x=HandoverItem(from_mandate_id=int(d["fromMandateId"]),to_mandate_id=int(d["toMandateId"]),role_id=int(d["roleId"]),title=d["title"].strip(),notes=d.get("notes"))
        except (KeyError,TypeError,ValueError):return {"error":"Données de transmission incomplètes."},400
        db.session.add(x);db.session.commit();return handover_payload(x),201

    @app.patch("/api/handovers/<int:item_id>/confirm")
    def handover_confirm(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(HandoverItem,item_id)
        if not x:return {"error":"Transmission introuvable."},404
        d=request.get_json(silent=True) or {};side=d.get("side")
        if account.is_system_admin:
            allowed=True
        else:
            mandate_id=x.from_mandate_id if side=="outgoing" else x.to_mandate_id
            allowed=RoleAssignment.query.filter_by(mandate_id=mandate_id,role_id=x.role_id,member_id=account.member_id,status="ACTIVE").first() is not None
        if not allowed:return {"error":"Cette validation appartient au responsable de la fonction."},403
        if side=="outgoing":x.outgoing_confirmed_at=datetime.utcnow()
        elif side=="incoming":x.incoming_confirmed_at=datetime.utcnow()
        else:return {"error":"Sens de validation invalide."},400
        audit(account,"HANDOVER_CONFIRMED","handover",x.id,f"side={side}")
        db.session.commit();return handover_payload(x)

    def board_member(account):
        if account.is_system_admin:return True
        today=date.today();mandate=Mandate.query.filter(Mandate.start_date<=today,Mandate.end_date>=today).order_by(Mandate.start_date.desc()).first()
        if not mandate:return False
        allowed=["président","president","vice-président","vice president","vice-president","secrétaire trésorier","secretaire tresorier","secrétaire-trésorier","secretaire-tresorier","trésorier","tresorier"]
        assignments=RoleAssignment.query.filter_by(mandate_id=mandate.id,member_id=account.member_id,status="ACTIVE").all()
        return any((db.session.get(Role,x.role_id) and db.session.get(Role,x.role_id).name.lower().strip() in allowed) for x in assignments)

    def current_role_ids(account):
        today=date.today();mandates=Mandate.query.filter(Mandate.start_date<=today,Mandate.end_date>=today).all()
        mids=[m.id for m in mandates]
        if not mids:return set()
        return {x.role_id for x in RoleAssignment.query.filter(RoleAssignment.mandate_id.in_(mids),RoleAssignment.member_id==account.member_id,RoleAssignment.status=="ACTIVE").all()}

    def can_view_library_item(account,role_id,board_only):
        if account.is_system_admin:return True
        if board_only and not board_member(account):return False
        return not role_id or role_id in current_role_ids(account)

    CHAPTER_DOCUMENT_EXTENSIONS={"pdf","doc","docx","xls","xlsx","ppt","pptx","png","jpg","jpeg","webp"}
    CHAPTER_DOCUMENT_MAX_SIZE=5*1024*1024

    def chapter_document_payload(x,current_mandate_id=None):
        mandate=db.session.get(Mandate,x.mandate_id)
        author=db.session.get(Member,x.uploaded_by_member_id) if x.uploaded_by_member_id else None
        return {"id":x.id,"title":x.title,"description":x.description,"category":x.category,"fileName":x.file_name,"fileType":x.file_type,"createdAt":x.created_at.isoformat(),"uploadedBy":f"{author.first_name} {author.last_name}" if author else "Comité","mandate":{"id":mandate.id,"name":mandate.name,"startDate":mandate.start_date.isoformat(),"endDate":mandate.end_date.isoformat()} if mandate else None,"current":bool(mandate and current_mandate_id==mandate.id)}

    @app.get("/api/documents")
    def chapter_documents_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        current=active_mandate()
        rows=ChapterDocument.query.filter_by(active=True).order_by(ChapterDocument.created_at.desc()).all()
        return jsonify([chapter_document_payload(x,current.id if current else None) for x in rows])

    @app.post("/api/documents/upload")
    def chapter_documents_upload():
        account,err=require_admin()
        if err:return err
        mandate=active_mandate()
        if not mandate:return {"error":"Aucune mandature active. Impossible de rattacher le document."},400
        file=request.files.get("file")
        if not file or not file.filename:return {"error":"Fichier obligatoire."},400
        ext=file.filename.rsplit(".",1)[-1].lower() if "." in file.filename else ""
        if ext not in CHAPTER_DOCUMENT_EXTENSIONS:return {"error":"Type de fichier non autorisé."},400
        data=file.read(CHAPTER_DOCUMENT_MAX_SIZE+1)
        if len(data)>CHAPTER_DOCUMENT_MAX_SIZE:return {"error":"Le fichier dépasse 5 Mo."},413
        title=(request.form.get("title") or file.filename).strip()
        if not title:return {"error":"Titre obligatoire."},400
        x=ChapterDocument(mandate_id=mandate.id,uploaded_by_member_id=account.member_id,title=title,description=(request.form.get("description") or "").strip() or None,category=(request.form.get("category") or "AUTRE").strip().upper(),file_name=file.filename,file_type=file.mimetype or "application/octet-stream",file_data=data)
        db.session.add(x);db.session.flush();audit(account,"CHAPTER_DOCUMENT_PUBLISHED","chapter_document",x.id,f"{x.file_name}; mandate={mandate.id}");db.session.commit()
        return chapter_document_payload(x,mandate.id),201

    @app.get("/api/documents/<int:item_id>/file")
    def chapter_document_file(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(ChapterDocument,item_id)
        if not x or not x.active:return {"error":"Document introuvable."},404
        return send_file(io.BytesIO(x.file_data),mimetype=x.file_type or "application/octet-stream",download_name=x.file_name,as_attachment=True)

    @app.delete("/api/documents/<int:item_id>")
    def chapter_document_archive(item_id):
        account,err=require_admin()
        if err:return err
        x=db.session.get(ChapterDocument,item_id)
        if not x:return {"error":"Document introuvable."},404
        x.active=False;audit(account,"CHAPTER_DOCUMENT_ARCHIVED","chapter_document",x.id,x.title);db.session.commit()
        return {"status":"archived"}

    def vault_cipher():
        key=os.getenv("VAULT_KEY","").strip()
        if not key:return None
        try:return Fernet(key.encode())
        except Exception:return None

    def require_board():
        account,_=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if not (account.is_system_admin or board_member(account)):return None,({"error":"Accès réservé au comité directeur."},403)
        return account,None

    def vault_value(cipher,value):
        if not value:return ""
        try:return cipher.decrypt(value).decode()
        except (InvalidToken,ValueError):return ""

    @app.route("/api/vault",methods=["GET","POST"])
    def vault_collection():
        account,err=require_board()
        if err:return err
        cipher=vault_cipher()
        if not cipher:return {"error":"Le coffre sécurisé n'est pas configuré."},503
        if request.method=="POST":
            d=request.get_json(silent=True) or {}
            if not (d.get("name") or "").strip():return {"error":"Nom obligatoire."},400
            x=VaultEntry(name=d["name"].strip(),url=(d.get("url") or "").strip() or None,username_encrypted=cipher.encrypt((d.get("username") or "").encode()),password_encrypted=cipher.encrypt((d.get("password") or "").encode()),notes_encrypted=cipher.encrypt((d.get("notes") or "").encode()))
            db.session.add(x);db.session.flush();audit(account,"VAULT_ENTRY_CREATED","vault_entry",x.id,x.name);db.session.commit()
            return {"id":x.id,"name":x.name},201
        rows=VaultEntry.query.filter_by(active=True).order_by(VaultEntry.name).all()
        return jsonify([{"id":x.id,"name":x.name,"url":x.url,"username":vault_value(cipher,x.username_encrypted),"password":vault_value(cipher,x.password_encrypted),"notes":vault_value(cipher,x.notes_encrypted)} for x in rows])

    @app.patch("/api/vault/<int:item_id>")
    def vault_update(item_id):
        account,err=require_board()
        if err:return err
        cipher=vault_cipher()
        if not cipher:return {"error":"Le coffre sécurisé n'est pas configuré."},503
        x=db.session.get(VaultEntry,item_id)
        if not x or not x.active:return {"error":"Accès introuvable."},404
        d=request.get_json(silent=True) or {}
        if "name" in d:x.name=(d["name"] or "").strip() or x.name
        if "url" in d:x.url=(d["url"] or "").strip() or None
        if "username" in d:x.username_encrypted=cipher.encrypt((d["username"] or "").encode())
        if "password" in d:x.password_encrypted=cipher.encrypt((d["password"] or "").encode())
        if "notes" in d:x.notes_encrypted=cipher.encrypt((d["notes"] or "").encode())
        audit(account,"VAULT_ENTRY_UPDATED","vault_entry",x.id,x.name);db.session.commit();return {"status":"ok"}

    @app.delete("/api/vault/<int:item_id>")
    def vault_delete(item_id):
        account,err=require_board()
        if err:return err
        x=db.session.get(VaultEntry,item_id)
        if not x:return {"error":"Accès introuvable."},404
        x.active=False;audit(account,"VAULT_ENTRY_ARCHIVED","vault_entry",x.id,x.name);db.session.commit();return {"status":"archived"}

    ALLOWED_RESOURCE_EXTENSIONS={"pdf","doc","docx","xls","xlsx","png","jpg","jpeg","webp"}
    def resource_meta(x):
        return {"id":x.id,"title":x.title,"description":x.description,"category":x.category,"url":x.url,"roleId":x.role_id,"boardOnly":x.board_only,"fileName":x.file_name,"hasFile":bool(x.file_data)}

    @app.post("/api/resources/upload")
    def resources_upload():
        _,err=require_admin()
        if err:return err
        file=request.files.get("file")
        if not file or not file.filename:return {"error":"Fichier obligatoire."},400
        ext=file.filename.rsplit(".",1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_RESOURCE_EXTENSIONS:return {"error":"Type de fichier non autorisé."},400
        data=file.read()
        if len(data)>5*1024*1024:return {"error":"Fichier trop volumineux (5 Mo maximum)."},413
        x=Resource(title=(request.form.get("title") or file.filename).strip(),description=request.form.get("description"),category=request.form.get("category") or "GENERAL",role_id=int(request.form["roleId"]) if request.form.get("roleId") else None,board_only=request.form.get("boardOnly")=="true",file_name=file.filename,file_type=file.mimetype,file_data=data)
        db.session.add(x);db.session.flush();audit(_, "RESOURCE_FILE_UPLOADED","resource",x.id,x.file_name);db.session.commit();return resource_meta(x),201

    @app.get("/api/resources/<int:item_id>/file")
    def resource_file(item_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(Resource,item_id)
        if not x or not x.active or not x.file_data:return {"error":"Fichier introuvable."},404
        if not can_view_library_item(account,x.role_id,x.board_only):return {"error":"Accès refusé."},403
        return send_file(io.BytesIO(x.file_data),mimetype=x.file_type or "application/octet-stream",download_name=x.file_name or "ressource",as_attachment=True)

    @app.get("/api/resources")
    def resources_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=Resource.query.filter_by(active=True).order_by(Resource.category,Resource.title).all()
        return jsonify([resource_meta(x) for x in rows if can_view_library_item(account,x.role_id,x.board_only)])

    @app.post("/api/resources")
    def resources_create():
        _,err=require_admin()
        if err:return err
        d=request.get_json(silent=True) or {}
        if not d.get("title"):return {"error":"Titre obligatoire."},400
        x=Resource(title=d["title"].strip(),description=d.get("description"),category=d.get("category","GENERAL"),url=d.get("url"),role_id=d.get("roleId") or None,board_only=bool(d.get("boardOnly",False)))
        db.session.add(x);db.session.commit();return {"id":x.id},201

    @app.patch("/api/resources/<int:item_id>")
    def resources_update(item_id):
        _,err=require_admin()
        if err:return err
        x=db.session.get(Resource,item_id)
        if not x:return {"error":"Ressource introuvable."},404
        d=request.get_json(silent=True) or {}
        for key,attr in [("title","title"),("description","description"),("category","category"),("url","url")]:
            if key in d:setattr(x,attr,d[key])
        if "roleId" in d:x.role_id=d.get("roleId") or None
        if "boardOnly" in d:x.board_only=bool(d["boardOnly"])
        if "active" in d:x.active=bool(d["active"])
        db.session.commit();return {"status":"ok"}

    @app.delete("/api/resources/<int:item_id>")
    def resources_delete(item_id):
        _,err=require_admin()
        if err:return err
        x=db.session.get(Resource,item_id)
        if not x:return {"error":"Ressource introuvable."},404
        x.active=False;audit(_, "RESOURCE_ARCHIVED","resource",x.id,x.title);db.session.commit();return {"status":"archived"}

    @app.get("/api/platforms")
    def platforms_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=Platform.query.filter_by(active=True).order_by(Platform.name).all()
        return jsonify([{"id":x.id,"name":x.name,"description":x.description,"url":x.url,"ownerRoleId":x.owner_role_id,"boardOnly":x.board_only,"renewalInfo":x.renewal_info} for x in rows if can_view_library_item(account,x.owner_role_id,x.board_only)])

    @app.post("/api/platforms")
    def platforms_create():
        _,err=require_admin()
        if err:return err
        d=request.get_json(silent=True) or {}
        if not d.get("name"):return {"error":"Nom obligatoire."},400
        x=Platform(name=d["name"].strip(),description=d.get("description"),url=d.get("url"),owner_role_id=d.get("ownerRoleId") or None,board_only=bool(d.get("boardOnly",False)),renewal_info=d.get("renewalInfo"))
        db.session.add(x);db.session.flush();audit(_, "PLATFORM_CREATED","platform",x.id,x.name);db.session.commit();return {"id":x.id},201

    @app.patch("/api/platforms/<int:item_id>")
    def platforms_update(item_id):
        _,err=require_admin()
        if err:return err
        x=db.session.get(Platform,item_id)
        if not x:return {"error":"Plateforme introuvable."},404
        d=request.get_json(silent=True) or {}
        for key,attr in [("name","name"),("description","description"),("url","url"),("renewalInfo","renewal_info")]:
            if key in d:setattr(x,attr,d[key])
        if "ownerRoleId" in d:x.owner_role_id=d.get("ownerRoleId") or None
        if "boardOnly" in d:x.board_only=bool(d["boardOnly"])
        if "active" in d:x.active=bool(d["active"])
        audit(_, "PLATFORM_UPDATED","platform",x.id,x.name);db.session.commit();return {"status":"ok"}

    @app.delete("/api/platforms/<int:item_id>")
    def platforms_delete(item_id):
        _,err=require_admin()
        if err:return err
        x=db.session.get(Platform,item_id)
        if not x:return {"error":"Plateforme introuvable."},404
        x.active=False;audit(_, "PLATFORM_ARCHIVED","platform",x.id,x.name);db.session.commit();return {"status":"archived"}

    def require_alumni_access():
        account,_=bearer_account()
        if not account:return None,({"error":"Authentification requise."},401)
        if account.is_system_admin:return account,None
        today=date.today()
        mandate=Mandate.query.filter(Mandate.start_date<=today,Mandate.end_date>=today).order_by(Mandate.start_date.desc()).first()
        if not mandate:return account,({"error":"Aucune mandature active."},403)
        allowed=["président","president","vice-président","vice president","vice-president","secrétaire trésorier","secretaire tresorier","secrétaire-trésorier","secretaire-tresorier"]
        assignments=RoleAssignment.query.filter_by(mandate_id=mandate.id,member_id=account.member_id,status="ACTIVE").all()
        roles=[db.session.get(Role,x.role_id) for x in assignments]
        if any(r and r.name.lower().strip() in allowed for r in roles):return account,None
        return account,({"error":"Accès réservé au Board de la mandature active."},403)

    @app.get("/api/alumni")
    def alumni_list():
        _,err=require_alumni_access()
        if err:return err
        rows=db.session.query(Member,Membership).join(Membership,Membership.member_id==Member.id).filter(Membership.status.in_(["FORMER","ALUMNI"])).order_by(Member.last_name,Member.first_name).all()
        return jsonify([{"memberId":m.id,"firstName":m.first_name,"lastName":m.last_name,"company":m.company,"activity":m.activity,"email":m.email,"phone":m.phone,"startDate":ms.start_date.isoformat() if ms.start_date else None,"endDate":ms.end_date.isoformat() if ms.end_date else None} for m,ms in rows])

    @app.get("/api/alumni/export")
    def alumni_export():
        _,err=require_alumni_access()
        if err:return err
        from io import BytesIO
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active;ws.title="HUB Alumni"
        ws.append(["Prénom","Nom","Société","Activité","Email","Téléphone","Date entrée","Date sortie"])
        rows=db.session.query(Member,Membership).join(Membership,Membership.member_id==Member.id).filter(Membership.status.in_(["FORMER","ALUMNI"])).order_by(Member.last_name,Member.first_name).all()
        for m,ms in rows:ws.append([m.first_name,m.last_name,m.company,m.activity,m.email,m.phone,ms.start_date,ms.end_date])
        out=BytesIO();wb.save(out);out.seek(0)
        return send_file(out,as_attachment=True,download_name="BNI_Soignies_Alumni.xlsx",mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    ONBOARDING_DEFAULTS=[
        ("OBSERVE_SETUP","Observer la préparation de salle"),
        ("OBSERVE_RECEPTION","Observer l'accueil des invités"),
        ("OBSERVE_FOLLOWUP","Observer le suivi des invités"),
        ("INFOMERCIAL","Formation infomercial"),
        ("INVITATION","Formation invitation"),
        ("MENTOR_VALIDATION","Validation finale par le mentor"),
    ]

    def onboarding_payload(member_id):
        m=db.session.get(Member,member_id)
        membership=Membership.query.filter_by(member_id=member_id).order_by(Membership.id.desc()).first()
        mentorship=Mentorship.query.filter_by(member_id=member_id,status="ACTIVE").order_by(Mentorship.id.desc()).first()
        mentor=db.session.get(Member,mentorship.mentor_id) if mentorship else None
        steps=OnboardingStep.query.filter_by(member_id=member_id).order_by(OnboardingStep.id).all()
        return {"memberId":member_id,"member":f"{m.first_name} {m.last_name}" if m else "—","status":membership.status if membership else None,
          "mentorId":mentor.id if mentor else None,"mentor":f"{mentor.first_name} {mentor.last_name}" if mentor else None,
          "steps":[{"id":x.id,"code":x.code,"label":x.label,"completed":x.completed,"completedAt":x.completed_at.isoformat() if x.completed_at else None} for x in steps],
          "progress":round(100*sum(x.completed for x in steps)/len(steps)) if steps else 0}

    @app.get("/api/onboarding")
    def onboarding_list():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        ids=[x.member_id for x in Membership.query.filter(Membership.status=="ONBOARDING").all()]
        return jsonify([onboarding_payload(i) for i in ids])

    @app.post("/api/members/<int:member_id>/onboarding")
    def start_onboarding(member_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        try:mentor_id=int(data.get("mentorId"))
        except (TypeError,ValueError):return {"error":"Mentor obligatoire."},400
        if mentor_id==member_id or not db.session.get(Member,mentor_id):return {"error":"Mentor invalide."},400
        membership=Membership.query.filter_by(member_id=member_id).order_by(Membership.id.desc()).first()
        if not membership:return {"error":"Adhésion introuvable."},404
        membership.status="ONBOARDING"
        Mentorship.query.filter_by(member_id=member_id,status="ACTIVE").update({"status":"COMPLETED","completed_at":date.today()})
        db.session.add(Mentorship(member_id=member_id,mentor_id=mentor_id,status="ACTIVE",started_at=date.today()))
        existing={x.code for x in OnboardingStep.query.filter_by(member_id=member_id).all()}
        for code,label in ONBOARDING_DEFAULTS:
            if code not in existing:db.session.add(OnboardingStep(member_id=member_id,code=code,label=label))
        db.session.commit();return onboarding_payload(member_id),201

    @app.patch("/api/onboarding/<int:member_id>/steps/<int:step_id>")
    def onboarding_step(member_id,step_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        step=db.session.get(OnboardingStep,step_id)
        if not step or step.member_id!=member_id:return {"error":"Étape introuvable."},404
        mentorship=Mentorship.query.filter_by(member_id=member_id,status="ACTIVE").first()
        if not (account.is_system_admin or (mentorship and mentorship.mentor_id==account.member_id)):return {"error":"Validation réservée au mentor ou à l'administrateur."},403
        completed=bool((request.get_json(silent=True) or {}).get("completed",True))
        step.completed=completed;step.completed_at=datetime.utcnow() if completed else None
        db.session.commit();return onboarding_payload(member_id)

    @app.post("/api/onboarding/<int:member_id>/complete")
    def complete_onboarding(member_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        mentorship=Mentorship.query.filter_by(member_id=member_id,status="ACTIVE").first()
        if not (account.is_system_admin or (mentorship and mentorship.mentor_id==account.member_id)):return {"error":"Validation réservée au mentor ou à l'administrateur."},403
        steps=OnboardingStep.query.filter_by(member_id=member_id).all()
        if not steps or not all(x.completed for x in steps):return {"error":"Toutes les étapes doivent être validées."},400
        membership=Membership.query.filter_by(member_id=member_id).order_by(Membership.id.desc()).first()
        membership.status="ACTIVE"
        if mentorship:mentorship.status="COMPLETED";mentorship.completed_at=date.today()
        audit(account,"ONBOARDING_COMPLETED","member",member_id)
        notify(member_id,"ONBOARDING_COMPLETE","Intégration terminée","Votre mentor a validé votre intégration. Vous êtes maintenant membre autonome.","profile")
        db.session.commit();return onboarding_payload(member_id)

    @app.get("/api/audit")
    def audit_list():
        account,err=require_system_admin()
        if err:return err
        q=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
        out=[]
        for x in q:
            m=db.session.get(Member,x.member_id) if x.member_id else None
            out.append({"id":x.id,"actor":f"{m.first_name} {m.last_name}" if m else "Système","action":x.action,"entityType":x.entity_type,"entityId":x.entity_id,"details":x.details,"createdAt":x.created_at.isoformat()})
        return jsonify(out)

    @app.get("/api/mandates/readiness")
    def mandate_readiness():
        account,err=require_admin()
        if err:return err
        today=date.today();nxt=Mandate.query.filter(Mandate.start_date>today).order_by(Mandate.start_date.asc()).first()
        if not nxt:return {"ready":False,"blocking":["Aucune prochaine mandature n'est configurée."],"warnings":[]},200
        assignments=RoleAssignment.query.filter_by(mandate_id=nxt.id,status="ACTIVE").all()
        role_names={r.id:r.name for r in Role.query.all()}
        names=[role_names.get(a.role_id,"").lower() for a in assignments]
        blocking=[];warnings=[]
        if not any(n in {"président","president"} for n in names):blocking.append("Aucun Président n'est désigné pour la prochaine mandature.")
        if not assignments:blocking.append("Le futur comité ne contient encore aucune affectation.")
        duplicate_members={}
        for a in assignments:duplicate_members.setdefault(a.member_id,[]).append(a.role_id)
        multi=[mid for mid,rs in duplicate_members.items() if len(rs)>1]
        if multi:warnings.append(f"{len(multi)} membre(s) cumulent plusieurs fonctions dans la prochaine mandature.")
        handovers=HandoverItem.query.filter_by(to_mandate_id=nxt.id).all()
        incomplete=[x for x in handovers if not (x.outgoing_confirmed_at and x.incoming_confirmed_at)]
        if not handovers:warnings.append("Aucune checklist de passage de flambeau n'a encore été générée.")
        elif incomplete:warnings.append(f"{len(incomplete)} élément(s) de transmission restent à valider.")
        if nxt.start_date>today:
            days=(nxt.start_date-today).days
        else:days=0
        return {"ready":not blocking,"nextMandate":{"id":nxt.id,"name":nxt.name,"startDate":nxt.start_date.isoformat(),"endDate":nxt.end_date.isoformat()},"daysUntilStart":days,"assignments":len(assignments),"handoverTotal":len(handovers),"handoverIncomplete":len(incomplete),"blocking":blocking,"warnings":warnings,"systemAdminProtected":bool(account.is_system_admin)}

    @app.get("/api/mandates/status")
    def mandate_status():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        today=date.today();current=active_mandate(today)
        nxt=Mandate.query.filter(Mandate.start_date>today).order_by(Mandate.start_date.asc()).first()
        previous=Mandate.query.filter(Mandate.end_date<today).order_by(Mandate.end_date.desc()).first()
        def p(x):return None if not x else {"id":x.id,"name":x.name,"startDate":x.start_date.isoformat(),"endDate":x.end_date.isoformat()}
        return {"today":today.isoformat(),"current":p(current),"next":p(nxt),"previous":p(previous),"systemAdmin":bool(account.is_system_admin)}

    @app.get("/api/mandates")
    def mandates_list():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        rows=Mandate.query.order_by(Mandate.start_date.desc()).all()
        return jsonify([mandate_payload(x) for x in rows])

    @app.route("/api/roles",methods=["GET","POST"])
    def roles_api():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        if request.method=="POST":
            data=request.get_json(silent=True) or {};name=(data.get("name") or "").strip()
            if not name:return {"error":"Nom de fonction obligatoire."},400
            existing=Role.query.filter(db.func.lower(Role.name)==name.lower()).first()
            if existing:return {"id":existing.id,"name":existing.name}
            role=Role(name=name);db.session.add(role);db.session.commit()
            return {"id":role.id,"name":role.name},201
        return jsonify([{"id":r.id,"name":r.name} for r in Role.query.order_by(Role.name).all()])

    @app.post("/api/mandates/<int:mandate_id>/committee")
    def committee_add(mandate_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        mandate=db.session.get(Mandate,mandate_id)
        if not mandate:return {"error":"Mandat introuvable."},404
        data=request.get_json(silent=True) or {}
        try:member_id=int(data.get("memberId"));role_id=int(data.get("roleId"))
        except (TypeError,ValueError):return {"error":"Membre et fonction obligatoires."},400
        if not db.session.get(Member,member_id) or not db.session.get(Role,role_id):return {"error":"Membre ou fonction introuvable."},404
        assignment=RoleAssignment.query.filter_by(mandate_id=mandate_id,member_id=member_id,role_id=role_id).first()
        if assignment:assignment.status="ACTIVE"
        else:assignment=RoleAssignment(mandate_id=mandate_id,member_id=member_id,role_id=role_id,status="ACTIVE");db.session.add(assignment)
        db.session.commit();return mandate_payload(mandate),201

    @app.delete("/api/mandates/<int:mandate_id>/committee/<int:assignment_id>")
    def committee_remove(mandate_id,assignment_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        assignment=db.session.get(RoleAssignment,assignment_id)
        if not assignment or assignment.mandate_id!=mandate_id:return {"error":"Attribution introuvable."},404
        assignment.status="INACTIVE";db.session.commit();return {"status":"ok"}

    def confirmed_replacements(day):
        out=[];seen=set()
        for model in [AlumniSubstitution,AlumniReplacementNeed]:
            for row in model.query.filter_by(date=day,status="ACCEPTED").order_by(model.id).all():
                if not row.alumni_id or (row.alumni_id,row.official_id) in seen:continue
                seen.add((row.alumni_id,row.official_id))
                member=db.session.get(Member,row.alumni_id)
                out.append({"id":f"substitute-{row.alumni_id}-{row.official_id}","kind":"SUBSTITUTE","name":member_name(row.alumni_id),"company":member.company if member else None,"memberId":row.alumni_id,"replacesMemberId":row.official_id,"replaces":member_name(row.official_id)})
        return out

    def meeting_details_allowed(account,meeting):
        return official_member(account.member) or (alumni_member(account.member) and any(x['memberId']==account.member_id for x in confirmed_replacements(meeting.date)))

    def meeting_details_payload(meeting):
        assignments=DutyAssignment.query.filter(DutyAssignment.meeting_id==meeting.id,DutyAssignment.status.in_(["PUBLISHED","TO_REASSIGN"])).all()
        guests=NetworkVisitor.query.filter(NetworkVisitor.visit_date==meeting.date,NetworkVisitor.status!="DECLINED").all()
        legacy=MemberRequest.query.filter_by(type="INVITATION",event_date=meeting.date).all()
        names={g.name.strip().casefold() for g in guests}
        substitutes=confirmed_replacements(meeting.date) if meeting.status!="CANCELLED" and meeting.type!="NO_MEETING" else []
        return {**meeting_payload(meeting),"assignments":[assignment_payload(a) for a in assignments if official_member(db.session.get(Member,a.member_id))],
            "guests":[{"id":f"visitor-{g.id}","kind":"GUEST","name":g.name,"company":g.company,"invitedBy":member_name(g.invited_by_member_id)} for g in guests]+
                [{"id":f"request-{g.id}","kind":"GUEST","name":g.guest_name,"company":None,"invitedBy":member_name(g.member_id)} for g in legacy if g.guest_name and g.guest_name.strip().casefold() not in names]+substitutes}

    @app.get("/api/agenda/meetings/<int:meeting_id>")
    def agenda_meeting_details(meeting_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        meeting=db.session.get(Meeting,meeting_id)
        if not meeting:return {"error":"Réunion introuvable."},404
        if not meeting_details_allowed(account,meeting):return {"error":"Détails réservés aux membres et au suppléant confirmé pour cette réunion."},403
        data=meeting_details_payload(meeting)
        if not official_member(account.member):data.pop('notes',None)
        return data

    def meeting_payload(m):
        return {"id":m.id,"date":m.date.isoformat(),"startTime":m.start_time.strftime("%H:%M") if m.start_time else None,"type":m.type,"location":m.location,"status":m.status,"notes":m.notes}

    def assignment_payload(a):
        duty=db.session.get(Duty,a.duty_id);member=db.session.get(Member,a.member_id);meeting=db.session.get(Meeting,a.meeting_id)
        return {"id":a.id,"meetingId":a.meeting_id,"date":meeting.date.isoformat() if meeting else None,"dutyId":a.duty_id,"duty":duty.name if duty else "—","memberId":a.member_id,"member":f"{member.first_name} {member.last_name}" if member else "—","status":a.status}

    @app.get("/api/duties")
    def duties_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        return jsonify([{"id":d.id,"code":d.code,"name":d.name,"active":d.active} for d in Duty.query.order_by(Duty.id).all()])

    @app.get("/api/duty-assignments")
    def duty_assignments_list():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=DutyAssignment.query.join(Meeting,DutyAssignment.meeting_id==Meeting.id).order_by(Meeting.date,DutyAssignment.duty_id).all()
        return jsonify([assignment_payload(a) for a in rows])

    REQUEST_ROLE_HINTS={
        "INFOMERCIAL":["éducation","education","formation"],
        "COMMUNICATION":["réseaux sociaux","reseaux sociaux","communication"],
        "TRAINING":["éducation","education","formation"],
        "MENTORING":["mentor","mentorat"],
        "EVENT":["événement","evenement","events"],
        "INVITATION":["accueil","invité","invite"],
    }

    def request_assignees(kind,when=None):
        # Explicit admin routing takes priority over mandate-based automatic routing.
        configured=RequestRecipient.query.filter_by(request_type=kind).order_by(RequestRecipient.id).all()
        if configured:
            mids=list(dict.fromkeys([x.member_id for x in configured]))
            members={m.id:m for m in Member.query.filter(Member.id.in_(mids)).all()}
            return [{"memberId":mid,"member":f"{members[mid].first_name} {members[mid].last_name}","email":members[mid].email,"role":"Destinataire configuré"} for mid in mids if mid in members and official_member(members[mid])]
        when=when or date.today()
        mandates=Mandate.query.filter(Mandate.start_date<=when,Mandate.end_date>=when).all()
        if not mandates:return []
        hints=REQUEST_ROLE_HINTS.get(kind,[])
        roles=Role.query.all()
        role_ids=[r.id for r in roles if any(h in r.name.lower() for h in hints)]
        if not role_ids:return []
        rows=RoleAssignment.query.filter(RoleAssignment.mandate_id.in_([m.id for m in mandates]),RoleAssignment.role_id.in_(role_ids),RoleAssignment.status=="ACTIVE").all()
        members={m.id:m for m in Member.query.filter(Member.id.in_(list({a.member_id for a in rows}))).all()} if rows else {}
        rolemap={r.id:r.name for r in roles}
        return [{"memberId":a.member_id,"member":f"{members[a.member_id].first_name} {members[a.member_id].last_name}","email":members[a.member_id].email,"role":rolemap.get(a.role_id,"—")} for a in rows if a.member_id in members and official_member(members[a.member_id])]

    def can_manage_request(account,kind):
        if account.is_system_admin:return True
        if not official_member(account.member):return False
        return any(x["memberId"]==account.member_id for x in request_assignees(kind))

    def member_request_payload(x):
        m=db.session.get(Member,x.member_id);assignees=request_assignees(x.type,x.created_at.date() if x.created_at else None)
        return {"id":x.id,"type":x.type,"title":x.title,"message":x.message,"guestName":x.guest_name,"guestEmail":x.guest_email,"eventDate":x.event_date.isoformat() if x.event_date else None,"eventTime":x.event_time,"eventLocation":x.event_location,"status":x.status,"createdAt":x.created_at.isoformat(),"member":f"{m.first_name} {m.last_name}" if m else "—","assignees":[{k:v for k,v in t.items() if k!="email"} for t in assignees],"routingStatus":"ROUTED" if assignees else "UNASSIGNED","attachmentName":x.attachment_name,"hasAttachment":bool(x.attachment_data)}

    def notify(member_id,kind,title,message=None,link=None):
        n=Notification(member_id=member_id,type=kind,title=title,message=message,link=link)
        db.session.add(n);return n

    def notify_agenda_members(actor_id,title,message,event_date):
        for member in Member.query.join(UserAccount).filter(UserAccount.status=="ACTIVE").all():
            if member.id!=actor_id and (official_member(member) or alumni_member(member)):
                notify(member.id,"SHARED_EVENT",title,message,"agenda:"+event_date.strftime("%Y-%m"))

    def notification_payload(n):
        return {"id":n.id,"type":n.type,"title":n.title,"message":n.message,"link":n.link,"read":bool(n.read_at),"createdAt":n.created_at.isoformat()}

    @app.get("/api/me/notifications")
    def my_notifications():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=Notification.query.filter_by(member_id=account.member_id).order_by(Notification.created_at.desc()).limit(100).all()
        return {"unread":sum(not x.read_at for x in rows),"items":[notification_payload(x) for x in rows]}

    @app.post("/api/me/notifications/<int:notification_id>/read")
    def read_notification(notification_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        n=db.session.get(Notification,notification_id)
        if not n or n.member_id!=account.member_id:return {"error":"Notification introuvable."},404
        n.read_at=datetime.utcnow();db.session.commit();return notification_payload(n)

    @app.post("/api/me/notifications/read-all")
    def read_all_notifications():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        Notification.query.filter_by(member_id=account.member_id,read_at=None).update({"read_at":datetime.utcnow()})
        db.session.commit();return {"status":"ok"}

    REQUEST_ALLOWED_EXTENSIONS={"pdf","png","jpg","jpeg","webp","ppt","pptx","mp4","mov","m4v"}
    REQUEST_MAX_FILE_SIZE=5*1024*1024

    def send_simple_email(to_email,subject,body):
        host=os.getenv("SMTP_HOST","").strip();sender=os.getenv("SMTP_FROM","").strip()
        if not host or not sender or not to_email:return False
        msg=EmailMessage();msg["Subject"]=subject;msg["From"]=sender;msg["To"]=to_email;msg.set_content(body)
        port=int(os.getenv("SMTP_PORT","587"));user=os.getenv("SMTP_USER","").strip();password=os.getenv("SMTP_PASSWORD","")
        use_ssl=os.getenv("SMTP_SSL","false").lower() in {"1","true","yes"}
        smtp=(smtplib.SMTP_SSL(host,port,timeout=15) if use_ssl else smtplib.SMTP(host,port,timeout=15))
        try:
            if not use_ssl and os.getenv("SMTP_STARTTLS","true").lower() in {"1","true","yes"}:smtp.starttls()
            if user:smtp.login(user,password)
            smtp.send_message(msg);return True
        except Exception:
            app.logger.exception("Unable to send network email")
            return False
        finally:
            try:smtp.quit()
            except Exception:pass

    def network_email(source_id,target_id,kind,tab):
        # Only the recipient, never the encoder or the committees; no contact/business details.
        try:
            target=db.session.get(Member,target_id)
            source=db.session.get(Member,source_id)
            if not target or not source or source_id==target_id:return False
            email=target.user_account.email if target.user_account else target.email
            if not email:return False
            name=f"{source.first_name} {source.last_name}"
            link=HUB_APP_URL
            body=f"Bonjour {target.first_name},\n\nLe membre {name} t'a fait {kind}.\nOuvre ton app pour consulter :\n{link}/?network={tab}\n"
            return send_simple_email(email,f"Hub — {name} : {kind}",body)
        except Exception:
            app.logger.exception("Network email delivery failed")
            return False

    def referral_email(x):
        return network_email(x.from_member_id,x.to_member_id,"une recommandation","referrals")

    def send_request_email(x,account,targets):
        host=os.getenv("SMTP_HOST","").strip()
        sender=os.getenv("SMTP_FROM","").strip()
        if not host or not sender:return False
        recipients=list(dict.fromkeys([t.get("email") for t in targets if t.get("email")]))
        # Safety net: never silently drop an email when a request has no routed
        # responsible member (or the responsible member has no email yet).
        # The Hub keeps the request internally and sends it to the configured
        # fallback/admin mailbox so it can still be handled.
        if not recipients:
            fallback=(os.getenv("REQUEST_FALLBACK_EMAIL","").strip()
                      or os.getenv("SYSTEM_ADMIN_EMAIL","").strip()
                      or sender)
            if fallback:
                recipients=[fallback]
                app.logger.warning("Member request %s (%s) has no emailed assignee; using fallback recipient.",x.id,x.type)
        if not recipients:return False
        msg=EmailMessage()
        labels={"INFOMERCIAL":"Infomercial","COMMUNICATION":"Communication","TRAINING":"Formation","MENTORING":"Mentorat","EVENT":"Événement","INVITATION":"Invitation"}
        member=account.member
        msg["Subject"]=f"HUB Soignies — nouvelle demande {labels.get(x.type,x.type)}"
        msg["From"]=sender
        msg["To"]=", ".join(recipients)
        msg.set_content(f"""Nouvelle demande envoyée par {member.first_name} {member.last_name}.

Type : {labels.get(x.type,x.type)}
Sujet : {x.title or x.guest_name or "—"}
Message :
{x.message or "—"}

Cette demande est également disponible dans HUB Soignies.""")
        if x.attachment_data:
            maintype,subtype=(x.attachment_type or "application/octet-stream").split("/",1) if "/" in (x.attachment_type or "") else ("application","octet-stream")
            msg.add_attachment(x.attachment_data,maintype=maintype,subtype=subtype,filename=x.attachment_name or "piece-jointe")
        port=int(os.getenv("SMTP_PORT","587"))
        user=os.getenv("SMTP_USER","").strip();password=os.getenv("SMTP_PASSWORD","")
        use_ssl=os.getenv("SMTP_SSL","false").lower() in {"1","true","yes"}
        smtp=(smtplib.SMTP_SSL(host,port,timeout=15) if use_ssl else smtplib.SMTP(host,port,timeout=15))
        try:
            if not use_ssl and os.getenv("SMTP_STARTTLS","true").lower() in {"1","true","yes"}:smtp.starttls()
            if user:smtp.login(user,password)
            smtp.send_message(msg)
            return True
        finally:smtp.quit()

    @app.route("/api/me/requests",methods=["GET","POST"])
    def my_requests():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if request.method=="GET":
            rows=MemberRequest.query.filter_by(member_id=account.member_id).order_by(MemberRequest.created_at.desc()).all()
            return jsonify([member_request_payload(x) for x in rows])
        data=request.form if request.content_type and request.content_type.startswith("multipart/form-data") else (request.get_json(silent=True) or {})
        kind=(data.get("type") or "").strip().upper()
        allowed={"INFOMERCIAL","COMMUNICATION","TRAINING","MENTORING","EVENT","INVITATION"}
        if kind not in allowed:return {"error":"Type de demande invalide."},400
        event_date=None
        if data.get("eventDate"):
            try:event_date=date.fromisoformat(data["eventDate"])
            except ValueError:return {"error":"Date invalide."},400
        event_time=(data.get("eventTime") or "").strip() or None
        event_location=(data.get("eventLocation") or "").strip() or None
        if kind=="EVENT":
            if not event_date:return {"error":"La date de l'événement est obligatoire pour le publier dans l'agenda."},400
            if not str(data.get("title") or "").strip():return {"error":"Le titre de l'événement est obligatoire."},400
            if event_time:
                try:event_time=datetime.strptime(event_time,"%H:%M").strftime("%H:%M")
                except ValueError:return {"error":"Heure invalide."},400
            if event_location and len(event_location)>255:return {"error":"Le lieu ne peut pas dépasser 255 caractères."},400
        upload=request.files.get("attachment")
        attachment_name=attachment_type=None;attachment_data=None
        if upload and upload.filename:
            attachment_name=upload.filename
            ext=attachment_name.rsplit(".",1)[-1].lower() if "." in attachment_name else ""
            if ext not in REQUEST_ALLOWED_EXTENSIONS:return {"error":"Type de pièce jointe non autorisé. Utilisez une image, un PDF, un PowerPoint ou une mini-vidéo."},400
            attachment_data=upload.read(REQUEST_MAX_FILE_SIZE+1)
            if len(attachment_data)>REQUEST_MAX_FILE_SIZE:return {"error":"La pièce jointe dépasse 5 Mo."},413
            attachment_type=upload.mimetype or "application/octet-stream"
        x=MemberRequest(member_id=account.member_id,type=kind,title=(data.get("title") or "").strip() or None,message=(data.get("message") or "").strip() or None,guest_name=(data.get("guestName") or "").strip() or None,guest_email=(data.get("guestEmail") or "").strip() or None,event_date=event_date,attachment_name=attachment_name,attachment_type=attachment_type,attachment_data=attachment_data,status="TO_PROCESS")
        if kind=="EVENT":x.event_time=event_time;x.event_location=event_location
        db.session.add(x);db.session.flush()
        targets=request_assignees(kind)
        for target in targets:
            if target["memberId"]!=account.member_id:notify(target["memberId"],"NEW_REQUEST",f"Nouvelle demande : {kind.title()}",f"{account.member.first_name} {account.member.last_name} a envoyé une nouvelle demande.","requests")
        audit(account,"MEMBER_REQUEST_CREATED","member_request",x.id,f"type={kind}; attachment={attachment_name or 'none'}")
        if kind=="EVENT":
            notify_agenda_members(account.member_id,"Nouvel événement dans l’agenda",f"{account.member.first_name} {account.member.last_name} partage {x.title} le {event_date.strftime('%d/%m/%Y')}.",event_date)
        db.session.commit()
        email_sent=False
        try:email_sent=send_request_email(x,account,targets)
        except Exception as exc:
            app.logger.exception("Request email delivery failed: %s",exc)
        payload=member_request_payload(x);payload["emailSent"]=email_sent
        return payload,201

    @app.get("/api/member-requests/<int:request_id>/attachment")
    def member_request_attachment(request_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(MemberRequest,request_id)
        if not x or not x.attachment_data:return {"error":"Pièce jointe introuvable."},404
        shared_event=x.type=="EVENT" and x.event_date and (official_member(account.member) or alumni_member(account.member))
        if not (shared_event or account.is_system_admin or account.member_id==x.member_id or can_manage_request(account,x.type)):return {"error":"Accès refusé."},403
        return send_file(io.BytesIO(x.attachment_data),mimetype=x.attachment_type or "application/octet-stream",download_name=x.attachment_name or "piece-jointe",as_attachment=True)

    @app.route("/api/request-recipients",methods=["GET","PUT"])
    def request_recipients_config():
        account,err=require_admin()
        if err:return err
        allowed={"INFOMERCIAL","COMMUNICATION","TRAINING","MENTORING","EVENT","INVITATION"}
        if request.method=="GET":
            out={}
            for kind in allowed:
                configured=RequestRecipient.query.filter_by(request_type=kind).order_by(RequestRecipient.id).all()
                out[kind]=[x.member_id for x in configured]
            return jsonify(out)
        data=request.get_json(silent=True) or {}
        kind=(data.get("type") or "").strip().upper()
        if kind not in allowed:return {"error":"Type de demande invalide."},400
        raw=data.get("memberIds") or []
        try:mids=list(dict.fromkeys([int(x) for x in raw]))
        except (TypeError,ValueError):return {"error":"Liste de membres invalide."},400
        if mids:
            valid={m.id for m in Member.query.filter(Member.id.in_(mids)).all()}
            if len(valid)!=len(mids):return {"error":"Un ou plusieurs membres sont introuvables."},400
        RequestRecipient.query.filter_by(request_type=kind).delete()
        for mid in mids:db.session.add(RequestRecipient(request_type=kind,member_id=mid))
        audit(account,"REQUEST_RECIPIENTS_CHANGED","request_routing",kind,f"memberIds={mids}")
        db.session.commit()
        return {"type":kind,"memberIds":mids,"assignees":[{k:v for k,v in x.items() if k!="email"} for x in request_assignees(kind)]}

    @app.get("/api/member-requests")
    def all_member_requests():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=MemberRequest.query.order_by(MemberRequest.created_at.desc()).all()
        if not account.is_system_admin:
            rows=[x for x in rows if can_manage_request(account,x.type)]
        return jsonify([member_request_payload(x) for x in rows])

    @app.patch("/api/member-requests/<int:request_id>")
    def update_member_request(request_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(MemberRequest,request_id)
        if not x:return {"error":"Demande introuvable."},404
        if not can_manage_request(account,x.type):return {"error":"Cette demande relève d'une autre fonction."},403
        status=(request.get_json(silent=True) or {}).get("status")
        if status not in {"TO_PROCESS","IN_PROGRESS","COMPLETED"}:return {"error":"Statut invalide."},400
        x.status=status
        audit(account,"MEMBER_REQUEST_STATUS_CHANGED","member_request",x.id,f"status={status}")
        if x.member_id!=account.member_id:notify(x.member_id,"REQUEST_STATUS","Mise à jour de votre demande",f"Votre demande est maintenant : {status.replace('_',' ').lower()}.","my-requests")
        db.session.commit();return member_request_payload(x)

    @app.get("/api/me/requests/summary")
    def my_requests_summary():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=MemberRequest.query.filter_by(member_id=account.member_id).order_by(MemberRequest.created_at.desc()).all()
        counts={"TO_PROCESS":0,"IN_PROGRESS":0,"COMPLETED":0}
        for x in rows:counts[x.status]=counts.get(x.status,0)+1
        return {"total":len(rows),"counts":counts,"recent":[member_request_payload(x) for x in rows[:5]]}

    @app.get("/api/me/request-inbox")
    def my_request_inbox():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=MemberRequest.query.order_by(MemberRequest.created_at.desc()).all()
        return jsonify([member_request_payload(x) for x in rows if can_manage_request(account,x.type)])

    @app.get("/api/me/duty-assignments")
    def my_duty_assignments():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=DutyAssignment.query.join(Meeting,DutyAssignment.meeting_id==Meeting.id).filter(DutyAssignment.member_id==account.member_id,DutyAssignment.status.in_(["PUBLISHED","TO_REASSIGN"])).order_by(Meeting.date).all()
        return jsonify([assignment_payload(a) for a in rows])

    @app.post("/api/me/duty-assignments/<int:assignment_id>/unavailable")
    def my_duty_unavailable(assignment_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        a=db.session.get(DutyAssignment,assignment_id)
        if not a or a.member_id!=account.member_id:return {"error":"Affectation introuvable."},404
        if a.status!="PUBLISHED":return {"error":"Cette permanence n'est pas publiée."},400
        a.status="TO_REASSIGN";existing=SwapRequest.query.filter_by(assignment_id=a.id,status="OPEN").first()
        if not existing:db.session.add(SwapRequest(assignment_id=a.id,requester_id=account.member_id,status="OPEN"))
        meeting=db.session.get(Meeting,a.meeting_id);duty=db.session.get(Duty,a.duty_id)
        for m in Member.query.all():
            ms=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
            if official_member(m) and m.id!=account.member_id and ms and ms.status=="ACTIVE" and (not ms.start_date or ms.start_date<=meeting.date) and (not ms.end_date or ms.end_date>=meeting.date):
                notify(m.id,"DUTY_REPLACEMENT","Remplacement recherché",f"{account.member.first_name} {account.member.last_name} cherche un remplacement pour {duty.name} le {meeting.date.strftime('%d/%m/%Y')}.","duties")
        db.session.commit()
        return {"status":"TO_REASSIGN","message":"Indisponibilité enregistrée. Les autres membres peuvent proposer de reprendre cette permanence."}

    @app.get("/api/me/profile")
    def my_profile():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        m=account.member
        membership=active_membership_for(m.id)
        offer=OffMembership.query.filter_by(member_id=m.id,status="ACTIVE").order_by(OffMembership.id.desc()).first()
        subscription={"label":"Aucun forfait enregistré"}
        if offer:
            subscription={"label":OFF_PLANS.get(offer.plan_code,{}).get("label",offer.plan_code),"startsAt":offer.starts_at.isoformat() if offer.starts_at else None,"endsAt":offer.ends_at.isoformat() if offer.ends_at else None}
        elif membership:
            subscription={"label":"Membre OFF — aucun forfait OFF actif enregistré" if m.network_type=="OFF" else "Adhésion HUB" if membership.status in {"ACTIVE","ONBOARDING"} else "Ancien membre","startsAt":membership.start_date.isoformat() if membership.start_date else None,"endsAt":membership.end_date.isoformat() if membership.end_date else None}
        return {"id":m.id,"firstName":m.first_name,"lastName":m.last_name,"company":m.company,"activity":m.activity,"email":account.email,"phone":m.phone,"roles":account_payload(account)["roles"],"subscription":subscription}

    @app.route("/api/me/profile",methods=["PATCH"])
    def update_my_profile():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        data=request.get_json(silent=True) or {}
        m=account.member
        if "firstName" in data:m.first_name=(data["firstName"] or "").strip()
        if "lastName" in data:m.last_name=(data["lastName"] or "").strip()
        if not m.first_name or not m.last_name:return {"error":"Le prénom et le nom sont obligatoires."},400
        if "company" in data:m.company=(data["company"] or "").strip() or None
        if "activity" in data:m.activity=(data["activity"] or "").strip() or None
        if "phone" in data:m.phone=(data["phone"] or "").strip() or None
        if "email" in data:
            email=(data["email"] or "").strip().lower()
            if not email:return {"error":"L'adresse e-mail est obligatoire."},400
            other=UserAccount.query.filter(UserAccount.email==email,UserAccount.id!=account.id).first()
            if other:return {"error":"Cette adresse e-mail est déjà utilisée."},409
            account.email=email;m.email=email
        new_password=data.get("newPassword") or ""
        if new_password:
            if len(new_password)<10:return {"error":"Le nouveau mot de passe doit contenir au moins 10 caractères."},400
            current=data.get("currentPassword") or ""
            if not account.password_hash or not check_password_hash(account.password_hash,current):return {"error":"Mot de passe actuel incorrect."},403
            account.password_hash=generate_password_hash(new_password)
        audit(account,"MEMBER_PROFILE_UPDATED","member",m.id,"self-service profile update")
        db.session.commit()
        return {"status":"ok","profile":my_profile()}

    def swap_payload(x):
        a=db.session.get(DutyAssignment,x.assignment_id);meeting=db.session.get(Meeting,a.meeting_id) if a else None;duty=db.session.get(Duty,a.duty_id) if a else None;requester=db.session.get(Member,x.requester_id);volunteer=db.session.get(Member,x.volunteer_id) if x.volunteer_id else None
        return {"id":x.id,"assignmentId":x.assignment_id,"date":meeting.date.isoformat() if meeting else None,"duty":duty.name if duty else "—","requester":f"{requester.first_name} {requester.last_name}" if requester and official_member(requester) else "Poste à réattribuer","volunteer":f"{volunteer.first_name} {volunteer.last_name}" if volunteer else None,"status":x.status}

    @app.get("/api/swaps/open")
    def open_swaps():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=SwapRequest.query.filter_by(status="OPEN").order_by(SwapRequest.created_at).all()
        return jsonify([swap_payload(x) for x in rows if x.requester_id!=account.member_id])

    @app.post("/api/swaps/<int:swap_id>/volunteer")
    def volunteer_swap(swap_id):
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        x=db.session.get(SwapRequest,swap_id)
        if not x or x.status!="OPEN":return {"error":"Cette demande n'est plus disponible."},404
        if x.requester_id==account.member_id:return {"error":"Vous ne pouvez pas reprendre votre propre permanence."},400
        a=db.session.get(DutyAssignment,x.assignment_id)
        if DutyAssignment.query.filter(DutyAssignment.meeting_id==a.meeting_id,DutyAssignment.member_id==account.member_id,DutyAssignment.id!=a.id).first():return {"error":"Vous avez déjà une fonction lors de cette réunion."},409
        meeting=db.session.get(Meeting,a.meeting_id)
        ms=Membership.query.filter_by(member_id=account.member_id).order_by(Membership.id.desc()).first()
        if not ms or ms.status!="ACTIVE" or (ms.start_date and ms.start_date>meeting.date) or (ms.end_date and ms.end_date<meeting.date):return {"error":"Vous n'êtes pas membre actif à cette date."},403
        requester=x.requester_id;x.volunteer_id=account.member_id;x.status="ACCEPTED";a.member_id=account.member_id;a.status="PUBLISHED"
        notify(requester,"DUTY_REPLACED","Remplacement trouvé",f"{account.member.first_name} {account.member.last_name} reprend votre permanence du {meeting.date.strftime('%d/%m/%Y')}.","duties")
        notify(account.member_id,"DUTY_ASSIGNED","Permanence reprise",f"Vous êtes maintenant titulaire de cette permanence du {meeting.date.strftime('%d/%m/%Y')}.","duties")
        db.session.commit()
        return swap_payload(x)

    @app.patch("/api/duty-assignments/<int:assignment_id>")
    def update_duty_assignment(assignment_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        a=db.session.get(DutyAssignment,assignment_id)
        if not a:return {"error":"Affectation introuvable."},404
        data=request.get_json(silent=True) or {}
        if "memberId" in data:
            try:member_id=int(data["memberId"])
            except (TypeError,ValueError):return {"error":"Membre invalide."},400
            member=db.session.get(Member,member_id)
            if not member:return {"error":"Membre introuvable."},404
            meeting=db.session.get(Meeting,a.meeting_id)
            ms=Membership.query.filter_by(member_id=member_id).order_by(Membership.id.desc()).first()
            if not ms or ms.status!="ACTIVE" or (ms.start_date and ms.start_date>meeting.date) or (ms.end_date and ms.end_date<meeting.date):return {"error":"Membre non actif à cette date."},400
            if DutyAssignment.query.filter(DutyAssignment.meeting_id==a.meeting_id,DutyAssignment.member_id==member_id,DutyAssignment.id!=a.id).first():return {"error":"Ce membre a déjà une fonction ce jour-là."},409
            previous=a.member_id;a.member_id=member_id
            SwapRequest.query.filter_by(assignment_id=a.id,status="OPEN").update({"status":"CANCELLED"})
            if previous!=member_id:
                notify(previous,"DUTY_CHANGED","Permanence réattribuée",f"Votre permanence du {meeting.date.strftime('%d/%m/%Y')} a été réattribuée.","duties")
                notify(member_id,"DUTY_ASSIGNED","Nouvelle permanence",f"Une permanence vous a été attribuée le {meeting.date.strftime('%d/%m/%Y')}.","duties")
        db.session.commit();return assignment_payload(a)

    @app.post("/api/duty-assignments/<int:assignment_id>/reassign")
    def reassign_duty_assignment(assignment_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        a=db.session.get(DutyAssignment,assignment_id)
        if not a:return {"error":"Affectation introuvable."},404
        meeting=db.session.get(Meeting,a.meeting_id);duty=db.session.get(Duty,a.duty_id)
        occupied={x.member_id for x in DutyAssignment.query.filter_by(meeting_id=meeting.id).all() if x.id!=a.id}
        candidates=[]
        for m in Member.query.order_by(Member.last_name,Member.first_name).all():
            ms=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
            if official_member(m) and ms and ms.status=="ACTIVE" and m.id not in occupied and (not ms.start_date or ms.start_date<=meeting.date) and (not ms.end_date or ms.end_date>=meeting.date):candidates.append(m)
        if not candidates:return {"error":"Aucun membre disponible."},400
        def score(m):
            total=DutyAssignment.query.filter_by(member_id=m.id).count()
            specific=DutyAssignment.query.filter_by(member_id=m.id,duty_id=duty.id).count()
            return (total,specific,m.last_name.lower(),m.first_name.lower())
        candidates=[m for m in candidates if m.id!=a.member_id] or candidates
        candidates.sort(key=score);previous=a.member_id;a.member_id=candidates[0].id
        SwapRequest.query.filter_by(assignment_id=a.id,status="OPEN").update({"status":"CANCELLED"})
        notify(previous,"DUTY_CHANGED","Permanence réattribuée",f"Votre permanence du {meeting.date.strftime('%d/%m/%Y')} a été réattribuée.","duties")
        notify(a.member_id,"DUTY_ASSIGNED","Nouvelle permanence",f"Une permanence vous a été attribuée le {meeting.date.strftime('%d/%m/%Y')}.","duties")
        audit(_, "DUTY_REASSIGNED","duty_assignment",a.id,f"from={previous}; to={a.member_id}")
        db.session.commit();return assignment_payload(a)

    @app.get("/api/planning/welcome")
    def welcome_planning():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        rows=DutyAssignment.query.join(Meeting,DutyAssignment.meeting_id==Meeting.id).filter(DutyAssignment.status.in_(["PUBLISHED","TO_REASSIGN"])).order_by(Meeting.date,DutyAssignment.duty_id).all()
        grouped={}
        for a in rows:
            if not official_member(db.session.get(Member,a.member_id)):continue
            p=assignment_payload(a);key=p["date"]
            grouped.setdefault(key,{"date":key,"assignments":[]})["assignments"].append(p)
        return jsonify(list(grouped.values()))

    @app.post("/api/duty-assignments/generate")
    def generate_duty_assignments():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        try:start=date.fromisoformat(data.get("startDate",""));end=date.fromisoformat(data.get("endDate",""))
        except ValueError:return {"error":"Dates invalides."},400
        duties=Duty.query.filter_by(active=True).order_by(Duty.id).all()
        if not duties:return {"error":"Aucune fonction d'accueil configurée."},400
        meetings=Meeting.query.filter(Meeting.date>=start,Meeting.date<=end,Meeting.type!="NO_MEETING").order_by(Meeting.date).all()
        active_members=[]
        for m in Member.query.order_by(Member.last_name,Member.first_name).all():
            ms=Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first()
            if official_member(m) and ms and ms.status=="ACTIVE" and (not ms.end_date or ms.end_date>=start):active_members.append(m)
        if len(active_members)<len(duties):return {"error":"Pas assez de membres actifs pour générer la rotation."},400
        existing=DutyAssignment.query.join(Meeting,DutyAssignment.meeting_id==Meeting.id).filter(Meeting.date>=start,Meeting.date<=end).all()
        total={m.id:0 for m in active_members};per={(m.id,d.id):0 for m in active_members for d in duties};last={m.id:date.min for m in active_members}
        for a in existing:
            if a.member_id in total:
                total[a.member_id]+=1;per[(a.member_id,a.duty_id)]=per.get((a.member_id,a.duty_id),0)+1
                mt=db.session.get(Meeting,a.meeting_id)
                if mt and mt.date>last[a.member_id]:last[a.member_id]=mt.date
        created=0
        for mt in meetings:
            used={a.member_id for a in existing if a.meeting_id==mt.id}
            for duty in duties:
                if any(a.meeting_id==mt.id and a.duty_id==duty.id for a in existing):continue
                candidates=[m for m in active_members if m.id not in used and (not Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first().start_date or Membership.query.filter_by(member_id=m.id).order_by(Membership.id.desc()).first().start_date<=mt.date)]
                if not candidates:continue
                candidates.sort(key=lambda m:(total[m.id],per.get((m.id,duty.id),0),last[m.id],m.last_name.lower(),m.first_name.lower()))
                chosen=candidates[0]
                a=DutyAssignment(meeting_id=mt.id,duty_id=duty.id,member_id=chosen.id,status="DRAFT");db.session.add(a);existing.append(a);used.add(chosen.id);total[chosen.id]+=1;per[(chosen.id,duty.id)]=per.get((chosen.id,duty.id),0)+1;last[chosen.id]=mt.date;created+=1
        db.session.commit()
        return {"status":"ok","created":created}

    @app.post("/api/duty-assignments/publish")
    def publish_duty_assignments():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        try:start=date.fromisoformat(data.get("startDate",""));end=date.fromisoformat(data.get("endDate",""))
        except ValueError:return {"error":"Dates invalides."},400
        rows=DutyAssignment.query.join(Meeting,DutyAssignment.meeting_id==Meeting.id).filter(Meeting.date>=start,Meeting.date<=end,DutyAssignment.status=="DRAFT").all()
        for a in rows:a.status="PUBLISHED"
        audit(_, "DUTY_ASSIGNMENTS_PUBLISHED","duty_assignment",None,f"{start.isoformat()} to {end.isoformat()}; count={len(rows)}")
        db.session.commit();return {"status":"ok","published":len(rows)}

    @app.get("/api/agenda")
    def shared_agenda():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if not (official_member(account.member) or alumni_member(account.member)):return {"error":"Agenda réservé aux membres et anciens actifs."},403
        today=datetime.now(ZoneInfo("Europe/Brussels")).date()
        month=request.args.get("month",today.strftime("%Y-%m"))
        try:
            start=datetime.strptime(month,"%Y-%m").date().replace(day=1)
            end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
        except (ValueError,OverflowError):return {"error":"Mois invalide."},400
        items=[]
        for meeting in Meeting.query.filter(Meeting.date>=start,Meeting.date<end).order_by(Meeting.date).all():
            # A common calendar does not expose guest lists, private notes or board data.
            items.append({"id":"meeting-"+str(meeting.id),"meetingId":meeting.id,"detailsAvailable":meeting_details_allowed(account,meeting),"kind":"MEETING","date":meeting.date.isoformat(),"startTime":meeting.start_time.strftime("%H:%M") if meeting.start_time else None,"type":meeting.type,"status":meeting.status,"location":meeting.location})
        for event in MemberRequest.query.filter(MemberRequest.type=="EVENT",MemberRequest.event_date>=start,MemberRequest.event_date<end).order_by(MemberRequest.event_date,MemberRequest.id).all():
            owner=db.session.get(Member,event.member_id)
            items.append({"id":"event-"+str(event.id),"kind":"EVENT","date":event.event_date.isoformat(),"startTime":event.event_time,"location":event.event_location,"title":event.title or "Événement partagé","message":event.message,"member":member_name(event.member_id),"origin":"ALUMNI" if owner and (owner.network_type=="OFF" or alumni_member(owner)) else "MEMBERS","attachmentId":event.id if event.attachment_data else None,"attachmentName":event.attachment_name})
        next_role=None
        if official_member(account.member):
            own=DutyAssignment.query.join(Meeting,DutyAssignment.meeting_id==Meeting.id).filter(DutyAssignment.member_id==account.member_id,DutyAssignment.status.in_(["PUBLISHED","TO_REASSIGN"]),Meeting.date>=today,Meeting.status!="CANCELLED",Meeting.type!="NO_MEETING").order_by(Meeting.date,DutyAssignment.id).first()
            if own:
                meeting=db.session.get(Meeting,own.meeting_id)
                team=DutyAssignment.query.filter(DutyAssignment.meeting_id==own.meeting_id,DutyAssignment.status.in_(["PUBLISHED","TO_REASSIGN"])).order_by(DutyAssignment.id).all()
                next_role={"date":meeting.date.isoformat(),"startTime":meeting.start_time.strftime("%H:%M") if meeting.start_time else None,"location":meeting.location,"duties":[assignment_payload(a) for a in team if a.member_id==account.member_id],"team":[assignment_payload(a) for a in team if a.member_id!=account.member_id and official_member(db.session.get(Member,a.member_id))]}
        return {"month":start.strftime("%Y-%m"),"items":sorted(items,key=lambda x:(x["date"],x.get("startTime") or "",x["id"])),"nextRole":next_role}

    @app.route("/api/meetings",methods=["GET","POST"])
    def meetings():
        account,_=bearer_account()
        if not account:return {"error":"Authentification requise."},401
        if request.method=="POST":
            _,auth_error=require_admin()
            if auth_error:return auth_error
            data=request.get_json(silent=True) or {}
            try: meeting_date=date.fromisoformat(data.get("date",""))
            except ValueError:return {"error":"Date invalide."},400
            allowed={"REGULAR","NO_MEETING","EXTERNAL","HOSTED","JOINT","SPECIAL"}
            meeting_type=data.get("type","REGULAR")
            if meeting_type not in allowed:return {"error":"Type de réunion invalide."},400
            if Meeting.query.filter_by(date=meeting_date).first():return {"error":"Une entrée existe déjà à cette date."},409
            start=None
            if data.get("startTime"):
                try:start=datetime.strptime(data["startTime"],"%H:%M").time()
                except ValueError:return {"error":"Heure invalide."},400
            m=Meeting(date=meeting_date,start_time=start,type=meeting_type,location=(data.get("location") or "").strip() or None,status=data.get("status","PLANNED"),notes=(data.get("notes") or "").strip() or None)
            db.session.add(m);db.session.flush()
            if meeting_type in {"SPECIAL","EXTERNAL","HOSTED","JOINT"}:
                notify_agenda_members(account.member_id,"Nouvelle date spéciale du groupe",f"Une nouvelle date est partagée dans l’agenda du groupe le {m.date.strftime('%d/%m/%Y')}.",m.date)
            audit(_, "MEETING_CREATED","meeting",m.id,f"date={meeting_date.isoformat()}; type={meeting_type}");db.session.commit()
            return meeting_payload(m),201
        rows=Meeting.query.order_by(Meeting.date).all()
        return jsonify([meeting_payload(m) for m in rows])

    @app.route("/api/meetings/<int:meeting_id>",methods=["PATCH","DELETE"])
    def meeting_detail(meeting_id):
        _,auth_error=require_admin()
        if auth_error:return auth_error
        m=db.session.get(Meeting,meeting_id)
        if not m:return {"error":"Réunion introuvable."},404
        if request.method=="DELETE":
            audit(_, "MEETING_DELETED","meeting",m.id,f"date={m.date.isoformat()}");db.session.delete(m);db.session.commit();return {"status":"ok"}
        data=request.get_json(silent=True) or {}
        if "date" in data:
            try:m.date=date.fromisoformat(data["date"])
            except ValueError:return {"error":"Date invalide."},400
        if "type" in data:m.type=data["type"]
        if "location" in data:m.location=(data["location"] or "").strip() or None
        if "notes" in data:m.notes=(data["notes"] or "").strip() or None
        if "status" in data:m.status=data["status"]
        if "startTime" in data:
            try:m.start_time=datetime.strptime(data["startTime"],"%H:%M").time() if data["startTime"] else None
            except ValueError:return {"error":"Heure invalide."},400
        audit(_, "MEETING_UPDATED","meeting",m.id,f"date={m.date.isoformat()}; type={m.type}");db.session.commit();return meeting_payload(m)

    @app.post("/api/meetings/generate-thursdays")
    def generate_thursdays():
        _,auth_error=require_admin()
        if auth_error:return auth_error
        data=request.get_json(silent=True) or {}
        try:start=date.fromisoformat(data.get("startDate",""));end=date.fromisoformat(data.get("endDate",""))
        except ValueError:return {"error":"Dates invalides."},400
        if end<start:return {"error":"La date de fin doit suivre la date de début."},400
        d=start
        while d.weekday()!=3:d+=timedelta(days=1)
        created=0
        while d<=end:
            if not Meeting.query.filter_by(date=d).first():
                db.session.add(Meeting(date=d,start_time=datetime.strptime(data.get("startTime","07:00"),"%H:%M").time(),type="REGULAR",location=(data.get("location") or "").strip() or None,status="PLANNED"));created+=1
            d+=timedelta(days=7)
        db.session.commit()
        return {"status":"ok","created":created}

    with app.app_context():
        db.create_all()
        if db.engine.dialect.name=="postgresql":
            db.session.execute(text("ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS support_actor_id INTEGER"))
            db.session.execute(text("ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS support_parent_id INTEGER"))
            db.session.commit()
        if db.engine.dialect.name=="postgresql":
            db.session.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS alumni_bridge_enabled BOOLEAN NOT NULL DEFAULT FALSE"))
            db.session.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS alumni_requested_at TIMESTAMP"))
            db.session.commit()
        # Temporary lightweight migration until Alembic is introduced.
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE user_accounts ADD COLUMN IF NOT EXISTS is_system_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS network_type VARCHAR(30) NOT NULL DEFAULT 'OFFICIAL_BNI'"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE members ADD COLUMN IF NOT EXISTS network_access_enabled BOOLEAN NOT NULL DEFAULT FALSE"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE referrals ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_members_network_type ON members(network_type)"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE user_accounts ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(128)"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE user_accounts ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE member_requests ADD COLUMN IF NOT EXISTS attachment_name VARCHAR(255)"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE member_requests ADD COLUMN IF NOT EXISTS attachment_type VARCHAR(120)"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE member_requests ADD COLUMN IF NOT EXISTS attachment_data BYTEA"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE member_requests ADD COLUMN IF NOT EXISTS event_time VARCHAR(5)"))
        if db.engine.dialect.name=="postgresql":db.session.execute(text("ALTER TABLE member_requests ADD COLUMN IF NOT EXISTS event_location VARCHAR(255)"))
        db.session.commit()
        for key,last in [("amelie","loedt"),("simon","vanwymeersch"),("xavier","renaud")]:
            if not db.session.get(GuestVisitReviewer,key):
                def normalized_name(value):return unicodedata.normalize("NFKD",value or "").encode("ascii","ignore").decode().casefold().strip()
                matches=[m for m in Member.query.all() if official_member(m) and normalized_name(m.first_name)==key and normalized_name(m.last_name)==last]
                if len(matches)==1:db.session.add(GuestVisitReviewer(key=key,member_id=matches[0].id))
        db.session.commit()
        # Existing admitted OFF members move into the isolated alumni space too.
        # Release only future duties; historical attendance and activity stay intact.
        for member in Member.query.all():
            if alumni_member(member):release_future_welcome(member.id,date.today())
        db.session.commit()
        enabled_by_default={"REFERRALS","BUSINESS","ONE_TO_ONE","VISITORS","ATTENDANCE","ACTIVITY_SCORE"}
        for key,(label,desc) in V2_FEATURES.items():
            row=db.session.get(FeatureFlag,key)
            if not row:db.session.add(FeatureFlag(key=key,label=label,description=desc,enabled=(key in enabled_by_default)))
        db.session.commit()
        for m in Member.query.all():
            if not MemberNetworkHistory.query.filter_by(member_id=m.id).first():
                db.session.add(MemberNetworkHistory(member_id=m.id,network_type=m.network_type or "OFFICIAL_BNI",start_date=(m.created_at.date() if m.created_at else date.today())))
        db.session.commit()
        for code,name in [("SETUP","Préparation"),("RECEPTION","Accueil des invités"),("FOLLOWUP","Suivi des invités")]:
            duty=Duty.query.filter_by(code=code).first()
            if not duty:db.session.add(Duty(code=code,name=name,active=True))
        db.session.commit()
        # One-off launch rotation for the Hub presentation on Thursday 1 October 2026.
        # This is intentionally an exception: it seeds Amélie + Simon + Xavier once,
        # without changing the normal rotation algorithm for future meetings.
        launch_date=date(2026,10,1)
        launch_meeting=Meeting.query.filter_by(date=launch_date).first()
        if not launch_meeting:
            launch_meeting=Meeting(date=launch_date,start_time=datetime.strptime("07:00","%H:%M").time(),type="REGULAR",status="PLANNED",notes="Présentation HUB Soignies — rotation de lancement exceptionnelle")
            db.session.add(launch_meeting);db.session.flush()
        launch_people=[]
        for first in ["Amélie","Simon","Xavier"]:
            person=Member.query.filter(db.func.lower(Member.first_name)==first.lower()).order_by(Member.id).first()
            if person:launch_people.append(person)
        launch_duties=Duty.query.filter_by(active=True).order_by(Duty.id).limit(3).all()
        if len(launch_people)==3 and len(launch_duties)==3:
            for duty,person in zip(launch_duties,launch_people):
                exists=DutyAssignment.query.filter_by(meeting_id=launch_meeting.id,duty_id=duty.id).first()
                if not exists:db.session.add(DutyAssignment(meeting_id=launch_meeting.id,duty_id=duty.id,member_id=person.id,status="PUBLISHED"))
            db.session.commit()

        # Idempotent bootstrap of the first system administrator.
        admin_email=os.getenv("SYSTEM_ADMIN_EMAIL","").strip().lower()
        if admin_email:
            account=UserAccount.query.filter(db.func.lower(UserAccount.email)==admin_email).first()
            if account:
                account.is_system_admin=True
                membership=Membership.query.filter_by(member_id=account.member_id).order_by(Membership.id.asc()).first()
                if not membership:
                    membership=Membership(member_id=account.member_id,status="ACTIVE")
                    db.session.add(membership)
                membership.start_date=date(2017,4,1)
                membership.end_date=None
                membership.status="ACTIVE"
                mandate=Mandate.query.filter_by(name="Octobre 2026 - Mars 2027").first()
                if not mandate:
                    mandate=Mandate(name="Octobre 2026 - Mars 2027",start_date=date(2026,10,1),end_date=date(2027,3,31),status="PREPARATION")
                    db.session.add(mandate);db.session.flush()
                role=Role.query.filter(db.func.lower(Role.name)=="président").first()
                if not role:
                    role=Role(name="Président");db.session.add(role);db.session.flush()
                assignment=RoleAssignment.query.filter_by(mandate_id=mandate.id,role_id=role.id,member_id=account.member_id).first()
                if not assignment:
                    db.session.add(RoleAssignment(mandate_id=mandate.id,role_id=role.id,member_id=account.member_id,status="ACTIVE"))
                db.session.commit()
        if db.engine.dialect.name=="postgresql":
            try:repair_replacement_notifications()
            except Exception:
                db.session.rollback();app.logger.exception("HUB_SUPPLEANCE_REPAIR_FAILED")
    return app

app=create_app()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")))
