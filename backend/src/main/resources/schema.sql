create database if not exists copyright_studio default character set utf8mb4 collate utf8mb4_unicode_ci;
use copyright_studio;

create table if not exists foundation_profiles (
  id bigint primary key auto_increment, payload json not null, created_at timestamp default current_timestamp
);
create table if not exists app_settings (
  setting_key varchar(100) primary key, payload json not null,
  updated_at timestamp default current_timestamp on update current_timestamp
);
create table if not exists copyright_records (
  id bigint primary key auto_increment, name varchar(200) not null, short_name varchar(100), version varchar(50),
  owner varchar(200), industry varchar(100), completion_date date, status varchar(30) default '草稿',
  asset_path varchar(500), updated_at timestamp default current_timestamp on update current_timestamp,
  created_at timestamp default current_timestamp
);

create table if not exists project_foundations (
  copyright_id bigint primary key,
  payload json not null,
  updated_at timestamp default current_timestamp on update current_timestamp,
  constraint fk_foundation_copyright foreign key (copyright_id) references copyright_records(id) on delete cascade
);

create table if not exists project_ai_configs (
  copyright_id bigint primary key,
  payload json not null,
  updated_at timestamp default current_timestamp on update current_timestamp,
  constraint fk_ai_config_copyright foreign key (copyright_id) references copyright_records(id) on delete cascade
);

create table if not exists manual_workspaces (
  copyright_id bigint primary key,
  nodes json not null,
  connections json not null,
  `generated` json not null,
  updated_at timestamp default current_timestamp on update current_timestamp,
  constraint fk_workspace_copyright foreign key (copyright_id) references copyright_records(id) on delete cascade
);
