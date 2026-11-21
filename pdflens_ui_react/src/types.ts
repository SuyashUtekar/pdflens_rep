export type ExtractionOptions = {
  extract_tables: boolean;
  extract_images: boolean;
  extract_header: boolean;
  extract_footer: boolean;
  extract_hyperlinks: boolean;
  extract_footnotes: boolean;
};

export type ConfigOption = { id: string; label: string };

export type JobRecord = {
  request_id: string;
  filename: string;
  status: string;
  config: string;
  submitted_at: string;
  size: number;
  options: ExtractionOptions;
  retrieved_at?: string;
  result_filename?: string;
};

export type ConfigResponse = {
  configurations: ConfigOption[];
  callback_configured: boolean;
};
