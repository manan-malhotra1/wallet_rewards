/**
 * "View" affordance for a live config row (Epic 25 / Task 9). Opens a
 * read-only drawer rendering the config via the shared `ConfigDetail`. Reused
 * by the pricing / commission / tax / limit tables.
 */
"use client";

import { Eye } from "lucide-react";
import * as React from "react";

import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Tooltip } from "@/components/ui/tooltip";
import type { ConfigType } from "@/lib/api-types";

export function ConfigViewButton({
  configType,
  data,
  title,
  serviceNames,
}: {
  configType: ConfigType;
  data: Record<string, unknown>;
  title: string;
  /** `{ code: display_name }` so the Service field shows the name, not the code. */
  serviceNames?: Record<string, string>;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Tooltip content="View">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="View"
          onClick={() => setOpen(true)}
        >
          <Eye className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>{title}</DrawerTitle>
          </DrawerHeader>
          <DrawerBody>
            <ConfigDetail
              configType={configType}
              data={data}
              serviceNames={serviceNames}
            />
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    </>
  );
}
