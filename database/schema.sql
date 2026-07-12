create database if not exists smart_street_food_safety
  character set utf8mb4
  collate utf8mb4_unicode_ci;

use smart_street_food_safety;

set foreign_key_checks = 0;

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
  created_at timestamp not null default current_timestamp,
  primary key (role_id),
  constraint uq_roles_role_name unique (role_name),
  constraint chk_roles_role_name_not_blank check (char_length(trim(role_name)) > 0)
) engine=innodb;

create table users (
  user_id int not null auto_increment,
  role_id int not null,
  full_name varchar(120) not null,
  email varchar(150) not null,
  phone varchar(30) null,
  password_hash varchar(255) not null,
  status enum('active', 'inactive', 'suspended') not null default 'active',
  created_at timestamp not null default current_timestamp,
  updated_at timestamp not null default current_timestamp on update current_timestamp,
  primary key (user_id),
  constraint uq_users_email unique (email),
  constraint uq_users_phone unique (phone),
  constraint chk_users_full_name_not_blank check (char_length(trim(full_name)) > 0),
  constraint chk_users_email_not_blank check (char_length(trim(email)) > 0),
  constraint chk_users_password_hash_not_blank check (char_length(trim(password_hash)) > 0),
  constraint fk_users_role_id
    foreign key (role_id) references roles (role_id)
    on update cascade
    on delete restrict
) engine=innodb;

create index idx_users_role_id on users (role_id);
create index idx_users_status on users (status);
create index idx_users_created_at on users (created_at);

create table vendors (
  vendor_id int not null auto_increment,
  user_id int not null,
  business_name varchar(150) not null,
  license_number varchar(80) not null,
  license_expiry_date date null,
  national_id varchar(80) null,
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
    on delete restrict
) engine=innodb;

create index idx_vendors_created_at on vendors (created_at);
create index idx_vendors_license_expiry_date on vendors (license_expiry_date);

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
create index idx_inspections_created_at on inspections (created_at);

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
  status enum('open', 'under_review', 'resolved', 'rejected') not null default 'open',
  submitted_at timestamp not null default current_timestamp,
  resolved_at timestamp null,
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
  created_at timestamp not null default current_timestamp,
  completed_at timestamp null,
  primary key (action_id),
  constraint chk_corrective_actions_source check (inspection_id is not null or complaint_id is not null),
  constraint fk_corrective_actions_inspection_id
    foreign key (inspection_id) references inspections (inspection_id)
    on update cascade
    on delete set null,
  constraint fk_corrective_actions_complaint_id
    foreign key (complaint_id) references complaints (complaint_id)
    on update cascade
    on delete set null,
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
