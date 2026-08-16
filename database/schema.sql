create database if not exists smart_street_food_safety
  character set utf8mb4
  collate utf8mb4_unicode_ci;

use smart_street_food_safety;

set foreign_key_checks = 0;

drop table if exists role_audit_log;
drop table if exists street_food_stall_registrations;
drop table if exists corrective_actions;
drop table if exists reviews;
drop table if exists complaints;
drop table if exists complaint_types;
drop table if exists inspection_scores;
drop table if exists inspections;
drop table if exists inspection_criteria;
drop table if exists food_items;
drop table if exists food_categories;
drop table if exists inspectors;
drop table if exists stalls;
drop table if exists areas;
drop table if exists vendors;
drop table if exists users;
drop table if exists roles;

set foreign_key_checks = 1;

create table roles (
  role_id int not null auto_increment,
  role_name varchar(50) not null,
  description varchar(255) null,
  is_system tinyint(1) not null default 0,
  is_admin_tier tinyint(1) not null default 0,
  created_at timestamp not null default current_timestamp,
  primary key (role_id),
  constraint uq_roles_role_name unique (role_name),
  constraint chk_roles_role_name_not_blank check (char_length(trim(role_name)) > 0)
) engine=innodb;

create table permissions (
  permission_id int not null auto_increment,
  code varchar(100) not null,
  description varchar(255) null,
  primary key (permission_id),
  constraint uq_permissions_code unique (code),
  constraint chk_permissions_code_not_blank check (char_length(trim(code)) > 0)
) engine=innodb;

create table role_permissions (
  role_id int not null,
  permission_id int not null,
  primary key (role_id, permission_id),
  constraint fk_role_permissions_role_id
    foreign key (role_id) references roles (role_id)
    on update cascade
    on delete cascade,
  constraint fk_role_permissions_permission_id
    foreign key (permission_id) references permissions (permission_id)
    on update cascade
    on delete cascade
) engine=innodb;

create table users (
  user_id int not null auto_increment,
  role_id int not null,
  full_name varchar(120) not null,
  email varchar(150) not null,
  phone varchar(30) null,
  password_hash varchar(255) null,
  google_id varchar(255) null,
  auth_provider enum('local', 'google') not null default 'local',
  status enum('active', 'inactive', 'suspended') not null default 'active',
  email_verified_at datetime null,
  profile_photo_url varchar(255) null,
  bio text null,
  address varchar(255) null,
  date_of_birth date null,
  preferred_area_id int null,
  is_super_admin tinyint(1) not null default 0,
  email_classification enum('unclassified', 'student', 'official_diu', 'external') not null default 'unclassified',
  created_at timestamp not null default current_timestamp,
  updated_at timestamp not null default current_timestamp on update current_timestamp,
  primary key (user_id),
  constraint uq_users_email unique (email),
  constraint uq_users_phone unique (phone),
  constraint uq_users_google_id unique (google_id),
  constraint chk_users_full_name_not_blank check (char_length(trim(full_name)) > 0),
  constraint chk_users_email_not_blank check (char_length(trim(email)) > 0),
  constraint chk_users_password_hash_not_blank check (char_length(trim(password_hash)) > 0),
  constraint chk_users_password_or_google check (password_hash is not null or google_id is not null),
  constraint fk_users_role_id
    foreign key (role_id) references roles (role_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_users_role_id on users (role_id);
create index idx_users_status on users (status);
create index idx_users_created_at on users (created_at);
create index idx_users_preferred_area_id on users (preferred_area_id);

create table vendors (
  vendor_id int not null auto_increment,
  user_id int not null,
  business_name varchar(150) not null,
  license_number varchar(80) not null,
  license_expiry_date date null,
  national_id varchar(80) null,
  status enum('pending', 'approved', 'rejected', 'suspended') not null default 'approved',
  requested_stall_name varchar(150) null,
  requested_area_id int null,
  requested_address varchar(255) null,
  rejection_reason varchar(500) null,
  reviewed_by_user_id int null,
  reviewed_at datetime null,
  created_at timestamp not null default current_timestamp,
  primary key (vendor_id),
  constraint uq_vendors_user_id unique (user_id),
  constraint uq_vendors_license_number unique (license_number),
  constraint uq_vendors_national_id unique (national_id),
  constraint chk_vendors_business_name_not_blank check (char_length(trim(business_name)) > 0),
  constraint chk_vendors_license_number_not_blank check (char_length(trim(license_number)) > 0),
  constraint fk_vendors_user_id
    foreign key (user_id) references users (user_id)
    on update cascade
    on delete restrict,
  constraint fk_vendors_reviewed_by_user_id
    foreign key (reviewed_by_user_id) references users (user_id)
    on update cascade
    on delete set null
) engine=innodb;

create index idx_vendors_created_at on vendors (created_at);
create index idx_vendors_license_expiry_date on vendors (license_expiry_date);
create index idx_vendors_status on vendors (status);

create table role_audit_log (
  audit_id int not null auto_increment,
  target_user_id int not null,
  actor_user_id int null,
  old_role_id int null,
  new_role_id int not null,
  reason varchar(255) null,
  created_at timestamp not null default current_timestamp,
  primary key (audit_id),
  constraint fk_role_audit_log_target_user_id
    foreign key (target_user_id) references users (user_id)
    on update cascade
    on delete cascade,
  constraint fk_role_audit_log_actor_user_id
    foreign key (actor_user_id) references users (user_id)
    on update cascade
    on delete set null,
  constraint fk_role_audit_log_old_role_id
    foreign key (old_role_id) references roles (role_id)
    on update cascade
    on delete set null,
  constraint fk_role_audit_log_new_role_id
    foreign key (new_role_id) references roles (role_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_role_audit_log_target_user_id on role_audit_log (target_user_id);
create index idx_role_audit_log_created_at on role_audit_log (created_at);

create table areas (
  area_id int not null auto_increment,
  area_name varchar(120) not null,
  city varchar(100) not null,
  zone varchar(100) not null default '',
  latitude decimal(10,8) null,
  longitude decimal(11,8) null,
  created_at timestamp not null default current_timestamp,
  primary key (area_id),
  constraint uq_areas_area_city_zone unique (area_name, city, zone),
  constraint chk_areas_area_name_not_blank check (char_length(trim(area_name)) > 0),
  constraint chk_areas_city_not_blank check (char_length(trim(city)) > 0),
  constraint chk_areas_latitude check (latitude is null or latitude between -90 and 90),
  constraint chk_areas_longitude check (longitude is null or longitude between -180 and 180)
) engine=innodb;

create index idx_areas_city_zone on areas (city, zone);
create index idx_areas_created_at on areas (created_at);

-- users.preferred_area_id and vendors.requested_area_id both reference
-- this table, defined above, so their foreign keys are attached here
-- rather than inline in their own `create table` statements.
alter table users
  add constraint fk_users_preferred_area_id
  foreign key (preferred_area_id) references areas (area_id)
  on update cascade
  on delete set null;

alter table vendors
  add constraint fk_vendors_requested_area_id
  foreign key (requested_area_id) references areas (area_id)
  on update cascade
  on delete set null;

create table inspectors (
  inspector_id int not null auto_increment,
  user_id int not null,
  employee_code varchar(80) not null,
  designation varchar(100) null,
  assigned_area_id int null,
  created_at timestamp not null default current_timestamp,
  primary key (inspector_id),
  constraint uq_inspectors_user_id unique (user_id),
  constraint uq_inspectors_employee_code unique (employee_code),
  constraint chk_inspectors_employee_code_not_blank check (char_length(trim(employee_code)) > 0),
  constraint fk_inspectors_user_id
    foreign key (user_id) references users (user_id)
    on update cascade
    on delete restrict,
  constraint fk_inspectors_assigned_area_id
    foreign key (assigned_area_id) references areas (area_id)
    on update cascade
    on delete set null
) engine=innodb;

create index idx_inspectors_assigned_area_id on inspectors (assigned_area_id);
create index idx_inspectors_created_at on inspectors (created_at);

create table stalls (
  stall_id int not null auto_increment,
  vendor_id int not null,
  area_id int not null,
  stall_name varchar(150) not null,
  stall_code varchar(80) not null,
  address varchar(255) not null,
  latitude decimal(10,8) null,
  longitude decimal(11,8) null,
  photo_url varchar(1000) null,
  status enum('active', 'closed', 'suspended') not null default 'active',
  created_at timestamp not null default current_timestamp,
  primary key (stall_id),
  constraint uq_stalls_stall_code unique (stall_code),
  constraint chk_stalls_stall_name_not_blank check (char_length(trim(stall_name)) > 0),
  constraint chk_stalls_stall_code_not_blank check (char_length(trim(stall_code)) > 0),
  constraint chk_stalls_address_not_blank check (char_length(trim(address)) > 0),
  constraint chk_stalls_latitude check (latitude is null or latitude between -90 and 90),
  constraint chk_stalls_longitude check (longitude is null or longitude between -180 and 180),
  constraint fk_stalls_vendor_id
    foreign key (vendor_id) references vendors (vendor_id)
    on update cascade
    on delete restrict,
  constraint fk_stalls_area_id
    foreign key (area_id) references areas (area_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_stalls_vendor_id on stalls (vendor_id);
create index idx_stalls_area_id on stalls (area_id);
create index idx_stalls_status on stalls (status);
create index idx_stalls_created_at on stalls (created_at);

create table food_categories (
  category_id int not null auto_increment,
  category_name varchar(100) not null,
  description varchar(255) null,
  risk_level enum('low', 'medium', 'high') not null default 'medium',
  primary key (category_id),
  constraint uq_food_categories_category_name unique (category_name),
  constraint chk_food_categories_category_name_not_blank check (char_length(trim(category_name)) > 0)
) engine=innodb;

create index idx_food_categories_risk_level on food_categories (risk_level);

create table food_items (
  food_item_id int not null auto_increment,
  stall_id int not null,
  category_id int not null,
  item_name varchar(150) not null,
  price decimal(10,2) null,
  is_available boolean not null default true,
  created_at timestamp not null default current_timestamp,
  primary key (food_item_id),
  constraint uq_food_items_stall_category_item unique (stall_id, category_id, item_name),
  constraint chk_food_items_item_name_not_blank check (char_length(trim(item_name)) > 0),
  constraint chk_food_items_price check (price is null or price >= 0),
  constraint fk_food_items_stall_id
    foreign key (stall_id) references stalls (stall_id)
    on update cascade
    on delete cascade,
  constraint fk_food_items_category_id
    foreign key (category_id) references food_categories (category_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_food_items_stall_id on food_items (stall_id);
create index idx_food_items_category_id on food_items (category_id);
create index idx_food_items_created_at on food_items (created_at);
create index idx_food_items_is_available on food_items (is_available);

create table inspection_criteria (
  criteria_id int not null auto_increment,
  criteria_name varchar(150) not null,
  description varchar(255) null,
  max_score decimal(5,2) not null,
  weight decimal(5,2) not null default 1.00,
  is_active boolean not null default true,
  primary key (criteria_id),
  constraint uq_inspection_criteria_criteria_name unique (criteria_name),
  constraint chk_inspection_criteria_criteria_name_not_blank check (char_length(trim(criteria_name)) > 0),
  constraint chk_inspection_criteria_max_score check (max_score > 0),
  constraint chk_inspection_criteria_weight check (weight > 0)
) engine=innodb;

create index idx_inspection_criteria_is_active on inspection_criteria (is_active);

create table inspections (
  inspection_id int not null auto_increment,
  stall_id int not null,
  inspector_id int not null,
  inspection_date datetime not null,
  overall_score decimal(6,2) null,
  risk_level enum('low', 'medium', 'high', 'critical') null,
  reinspection_date date null,
  status enum('draft', 'submitted', 'approved', 'rejected') not null default 'draft',
  remarks text null,
  created_at timestamp not null default current_timestamp,
  primary key (inspection_id),
  constraint chk_inspections_overall_score check (overall_score is null or overall_score >= 0),
  constraint fk_inspections_stall_id
    foreign key (stall_id) references stalls (stall_id)
    on update cascade
    on delete restrict,
  constraint fk_inspections_inspector_id
    foreign key (inspector_id) references inspectors (inspector_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_inspections_stall_id on inspections (stall_id);
create index idx_inspections_inspector_id on inspections (inspector_id);
create index idx_inspections_inspection_date on inspections (inspection_date);
create index idx_inspections_status on inspections (status);
create index idx_inspections_risk_level on inspections (risk_level);
create index idx_inspections_reinspection_date on inspections (reinspection_date);
create index idx_inspections_created_at on inspections (created_at);
create index idx_inspections_stall_status_date on inspections (stall_id, status, inspection_date, inspection_id);

create table inspection_scores (
  score_id int not null auto_increment,
  inspection_id int not null,
  criteria_id int not null,
  score decimal(5,2) not null,
  comments varchar(255) null,
  primary key (score_id),
  constraint uq_inspection_scores_inspection_criteria unique (inspection_id, criteria_id),
  constraint chk_inspection_scores_score check (score >= 0),
  constraint fk_inspection_scores_inspection_id
    foreign key (inspection_id) references inspections (inspection_id)
    on update cascade
    on delete cascade,
  constraint fk_inspection_scores_criteria_id
    foreign key (criteria_id) references inspection_criteria (criteria_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_inspection_scores_inspection_id on inspection_scores (inspection_id);
create index idx_inspection_scores_criteria_id on inspection_scores (criteria_id);

create table complaint_types (
  complaint_type_id int not null auto_increment,
  type_name varchar(100) not null,
  description varchar(255) null,
  severity_level enum('low', 'medium', 'high', 'critical') not null default 'medium',
  primary key (complaint_type_id),
  constraint uq_complaint_types_type_name unique (type_name),
  constraint chk_complaint_types_type_name_not_blank check (char_length(trim(type_name)) > 0)
) engine=innodb;

create index idx_complaint_types_severity_level on complaint_types (severity_level);

create table complaints (
  complaint_id int not null auto_increment,
  stall_id int not null,
  complaint_type_id int not null,
  submitted_by_user_id int null,
  title varchar(150) not null,
  description text not null,
  status enum('submitted', 'under_review', 'investigation', 'action_required', 'resolved', 'rejected', 'closed') not null default 'submitted',
  submitted_at timestamp not null default current_timestamp,
  resolved_at timestamp null,
  admin_response text null,
  primary key (complaint_id),
  constraint chk_complaints_title_not_blank check (char_length(trim(title)) > 0),
  constraint fk_complaints_stall_id
    foreign key (stall_id) references stalls (stall_id)
    on update cascade
    on delete restrict,
  constraint fk_complaints_complaint_type_id
    foreign key (complaint_type_id) references complaint_types (complaint_type_id)
    on update cascade
    on delete restrict,
  constraint fk_complaints_submitted_by_user_id
    foreign key (submitted_by_user_id) references users (user_id)
    on update cascade
    on delete set null
) engine=innodb;

create index idx_complaints_stall_id on complaints (stall_id);
create index idx_complaints_complaint_type_id on complaints (complaint_type_id);
create index idx_complaints_submitted_by_user_id on complaints (submitted_by_user_id);
create index idx_complaints_status on complaints (status);
create index idx_complaints_submitted_at on complaints (submitted_at);
create index idx_complaints_resolved_at on complaints (resolved_at);

create table complaint_evidence (
  evidence_id int not null auto_increment,
  complaint_id int not null,
  uploaded_by int null,
  file_name varchar(255) not null,
  stored_file_name varchar(255) not null,
  file_type enum('image', 'video', 'audio', 'document') not null,
  mime_type varchar(150) not null,
  file_size int unsigned not null,
  storage_path varchar(500) not null,
  file_hash char(64) not null,
  evidence_description varchar(500) null,
  uploaded_at timestamp not null default current_timestamp,
  verification_status enum('pending', 'under_review', 'verified', 'rejected') not null default 'pending',
  verified_by int null,
  verified_at timestamp null,
  rejection_reason varchar(500) null,
  primary key (evidence_id),
  constraint chk_complaint_evidence_file_name_not_blank check (char_length(trim(file_name)) > 0),
  constraint chk_complaint_evidence_file_size_positive check (file_size > 0),
  constraint chk_complaint_evidence_file_hash_length check (char_length(file_hash) = 64),
  constraint fk_complaint_evidence_complaint_id
    foreign key (complaint_id) references complaints (complaint_id)
    on update cascade
    on delete cascade,
  constraint fk_complaint_evidence_uploaded_by
    foreign key (uploaded_by) references users (user_id)
    on update cascade
    on delete set null,
  constraint fk_complaint_evidence_verified_by
    foreign key (verified_by) references users (user_id)
    on update cascade
    on delete set null
) engine=innodb;

create index idx_complaint_evidence_complaint_id on complaint_evidence (complaint_id);
create index idx_complaint_evidence_uploaded_by on complaint_evidence (uploaded_by);
create index idx_complaint_evidence_verification_status on complaint_evidence (verification_status);

create table evidence_audit_logs (
  audit_id int not null auto_increment,
  evidence_id int not null,
  user_id int null,
  action enum('uploaded', 'viewed', 'downloaded', 'marked_under_review', 'verified', 'rejected') not null,
  action_time timestamp not null default current_timestamp,
  ip_address varchar(45) null,
  user_agent varchar(255) null,
  details varchar(255) null,
  primary key (audit_id),
  constraint fk_evidence_audit_logs_evidence_id
    foreign key (evidence_id) references complaint_evidence (evidence_id)
    on update cascade
    on delete cascade,
  constraint fk_evidence_audit_logs_user_id
    foreign key (user_id) references users (user_id)
    on update cascade
    on delete set null
) engine=innodb;

create index idx_evidence_audit_logs_evidence_id on evidence_audit_logs (evidence_id);
create index idx_evidence_audit_logs_action_time on evidence_audit_logs (action_time);

create table notifications (
  notification_id int not null auto_increment,
  user_id int not null,
  complaint_id int null,
  message varchar(255) not null,
  is_read tinyint(1) not null default 0,
  created_at timestamp not null default current_timestamp,
  primary key (notification_id),
  constraint chk_notifications_message_not_blank check (char_length(trim(message)) > 0),
  constraint fk_notifications_user_id
    foreign key (user_id) references users (user_id)
    on update cascade
    on delete cascade,
  constraint fk_notifications_complaint_id
    foreign key (complaint_id) references complaints (complaint_id)
    on update cascade
    on delete cascade
) engine=innodb;

create index idx_notifications_user_id_is_read on notifications (user_id, is_read);
create index idx_notifications_created_at on notifications (created_at);

create table reviews (
  review_id int not null auto_increment,
  stall_id int not null,
  user_id int not null,
  rating tinyint not null,
  review_text text null,
  status enum('visible', 'hidden', 'flagged') not null default 'visible',
  created_at timestamp not null default current_timestamp,
  primary key (review_id),
  constraint uq_reviews_stall_user unique (stall_id, user_id),
  constraint chk_reviews_rating check (rating between 1 and 5),
  constraint fk_reviews_stall_id
    foreign key (stall_id) references stalls (stall_id)
    on update cascade
    on delete cascade,
  constraint fk_reviews_user_id
    foreign key (user_id) references users (user_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_reviews_stall_id on reviews (stall_id);
create index idx_reviews_user_id on reviews (user_id);
create index idx_reviews_rating on reviews (rating);
create index idx_reviews_status on reviews (status);
create index idx_reviews_created_at on reviews (created_at);

create table corrective_actions (
  action_id int not null auto_increment,
  inspection_id int null,
  complaint_id int null,
  assigned_to_vendor_id int not null,
  action_description text not null,
  due_date date not null,
  status enum('pending', 'in_progress', 'completed', 'overdue', 'cancelled') not null default 'pending',
  completion_notes text null,
  evidence_path varchar(500) null,
  created_at timestamp not null default current_timestamp,
  completed_at timestamp null,
  primary key (action_id),
  constraint fk_corrective_actions_inspection_id
    foreign key (inspection_id) references inspections (inspection_id)
    on update cascade
    on delete restrict,
  constraint fk_corrective_actions_complaint_id
    foreign key (complaint_id) references complaints (complaint_id)
    on update cascade
    on delete restrict,
  constraint fk_corrective_actions_assigned_to_vendor_id
    foreign key (assigned_to_vendor_id) references vendors (vendor_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_corrective_actions_inspection_id on corrective_actions (inspection_id);
create index idx_corrective_actions_complaint_id on corrective_actions (complaint_id);
create index idx_corrective_actions_assigned_to_vendor_id on corrective_actions (assigned_to_vendor_id);
create index idx_corrective_actions_due_date on corrective_actions (due_date);
create index idx_corrective_actions_status on corrective_actions (status);
create index idx_corrective_actions_created_at on corrective_actions (created_at);
create index idx_corrective_actions_completed_at on corrective_actions (completed_at);

create table street_food_stall_registrations (
  registration_id int not null auto_increment,
  submitted_at datetime not null,
  vendor_name varchar(150) not null,
  phone_number varchar(30) not null,
  stall_name varchar(200) not null,
  area varchar(200) not null,
  full_address varchar(500) not null,
  food_category varchar(255) not null,
  food_items varchar(500) not null,
  average_price_bdt varchar(50) not null,
  food_covered enum('Yes', 'No') not null,
  clean_water_used enum('Yes', 'No') not null,
  waste_bin_available enum('Yes', 'No') not null,
  vendor_uses_gloves enum('Yes', 'No') not null,
  payment_method varchar(255) null,
  stall_photo_url varchar(1000) null,
  additional_comments text null,
  source_timestamp varchar(100) not null,
  created_at timestamp not null default current_timestamp,
  primary key (registration_id),
  constraint chk_registrations_vendor_name_not_blank
    check (char_length(trim(vendor_name)) > 0),
  constraint chk_registrations_phone_not_blank
    check (char_length(trim(phone_number)) > 0),
  constraint chk_registrations_stall_name_not_blank
    check (char_length(trim(stall_name)) > 0)
) engine=innodb;

create index idx_registrations_submitted_at
  on street_food_stall_registrations (submitted_at);
create index idx_registrations_phone_number
  on street_food_stall_registrations (phone_number);
create index idx_registrations_area
  on street_food_stall_registrations (area);
create index idx_registrations_stall_name
  on street_food_stall_registrations (stall_name);
