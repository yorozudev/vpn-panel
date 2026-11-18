import {
  HStack,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Text,
} from "@chakra-ui/react";
import { SignalIcon } from "@heroicons/react/24/outline";
import { useDashboard } from "contexts/DashboardContext";
import { FC } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";
import { NodesRealtime } from "./NodesRealtime";

export const NodesRealtimeModal: FC = () => {
  const { isShowingNodesRealtime, onShowingNodesRealtime } = useDashboard();
  const { t } = useTranslation();

  return (
    <Modal
      isOpen={isShowingNodesRealtime}
      onClose={() => onShowingNodesRealtime(false)}
      size="6xl"
      scrollBehavior="inside"
    >
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent mx="3" w="full" maxH="90vh">
        <ModalHeader pt={6} pr={12}>
          <HStack gap={2}>
            <Icon color="primary">
              <SignalIcon color="white" />
            </Icon>
            <Text fontWeight="semibold" fontSize="lg">
              {t("nodesRealtime.title")}
            </Text>
          </HStack>
          <Text fontSize="sm" color="gray.500" fontWeight="normal" mt={1}>
            {t("nodesRealtime.interval")}
          </Text>
        </ModalHeader>
        <ModalCloseButton mt={3} />
        <ModalBody pb={6}>
          {isShowingNodesRealtime && <NodesRealtime showHeader={false} />}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
};
